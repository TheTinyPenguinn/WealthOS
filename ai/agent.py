from __future__ import annotations

from datetime import datetime
import os

from ai.tools import TOOLS
from app.goals.sequencer import allocate_surplus, get_ef_status, get_monthly_burn
from app.insurance.audit import audit_health_cover, audit_life_cover, detect_endowment_traps
from app.tax.capital_gains import get_gains_summary, get_harvesting_alerts
from app.tax.deductions import current_financial_year, get_deductions_summary
from app.tax.regime_compare import compare_regimes
from app.utils.llm_client import call_llm

try:
    from langfuse import Langfuse
except Exception:
    Langfuse = None


SYSTEM = """You are WealthOS CFO — ruthless, mathematically precise.
User: {name}, Age: {age}, Risk: {risk}, Regime: {regime}, EF: {ef_status}.
RULES:
1. NEVER guess. Call the correct tool before answering any financial question.
2. Direct sentences only. State the number. State the verdict.
3. Purchases/loans: call simulate_loan + get_financial_snapshot.
4. Tax questions: call compare_tax_regimes + get_80c_gap.
5. End every response with ONE specific action the user should take today.
6. If EF is building: prefix any investment advice with the EF warning.
"""


def _safe_float(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _determine_risk(profile: dict) -> str:
    age = int(profile.get("age") or 0)
    target_ret = int(profile.get("target_retirement_age") or 60)
    ytr = target_ret - age
    if ytr < 5:
        return "conservative"
    if ytr < 15:
        return "balanced"
    return "aggressive"


def _income_and_regime(user_id: str, supabase):
    try:
        profile_res = supabase.table("user_profile").select("*").eq("user_id", user_id).limit(1).execute()
        if profile_res.data:
            p = profile_res.data[0]
            return _safe_float(p.get("monthly_income"), 0.0), p.get("tax_regime", "new")
    except Exception:
        pass

    try:
        settings_res = supabase.table("user_settings").select("salary").eq("user_id", user_id).limit(1).execute()
        salary = _safe_float(settings_res.data[0].get("salary"), 0.0) if settings_res.data else 0.0
    except Exception:
        salary = 0.0
    return salary, "new"


def get_user_profile(user_id: str, supabase) -> dict:
    try:
        profile_res = supabase.table("user_profile").select("*").eq("user_id", user_id).limit(1).execute()
        profile = profile_res.data[0] if profile_res.data else {}
    except Exception:
        profile = {}
    try:
        ef = get_ef_status(user_id, supabase)
    except Exception:
        ef = {"status": "building"}
    return {
        "name": profile.get("name", "User"),
        "age": int(profile.get("age") or 0),
        "risk": _determine_risk(profile),
        "regime": profile.get("tax_regime", "new"),
        "ef_status": ef.get("status", "building"),
    }


def _financial_snapshot(user_id: str, supabase) -> dict:
    burn = get_monthly_burn(user_id, supabase)
    monthly_income, _ = _income_and_regime(user_id, supabase)
    surplus = monthly_income - burn

    acc_rows = supabase.table("accounts").select("*").eq("user_id", user_id).execute().data or []
    inv_rows = supabase.table("investments").select("*").eq("user_id", user_id).execute().data or []
    obligations = supabase.table("obligations").select("*").eq("user_id", user_id).execute().data or []

    bank_cash = sum(_safe_float(r.get("balance"), 0.0) for r in acc_rows if r.get("type") == "Bank/Cash")
    cc = sum(abs(_safe_float(r.get("balance"), 0.0)) for r in acc_rows if r.get("type") == "Credit Card")
    manual_inv = sum(_safe_float(r.get("balance"), 0.0) for r in acc_rows if "Investment" in str(r.get("type", "")))
    market_inv = sum(_safe_float(r.get("quantity"), 0.0) * _safe_float(r.get("avg_buy_price"), 0.0) for r in inv_rows)
    loan_balance = sum(_safe_float(r.get("current_balance"), 0.0) for r in obligations if str(r.get("type")).lower() == "loan")
    high_apr_emi = sum(
        _safe_float(r.get("monthly_emi"), 0.0)
        for r in obligations
        if _safe_float(r.get("interest_rate"), 0.0) > 12.0
    )

    liquid_nw = bank_cash + manual_inv + market_inv - loan_balance - cc
    runway = liquid_nw / burn if burn > 0 else 0.0
    return {
        "liquid_nw": liquid_nw,
        "liquid_net_worth": liquid_nw,
        "monthly_income": monthly_income,
        "monthly_burn": burn,
        "surplus": surplus,
        "monthly_savings": surplus,
        "high_apr_emi": high_apr_emi,
        "runway_months": runway,
    }


def get_financial_snapshot(user_id: str, supabase) -> dict:
    return _financial_snapshot(user_id, supabase)


def _simulate_loan(user_id: str, supabase, principal: float, apr: float, tenure_months: int) -> dict:
    principal = max(0.0, _safe_float(principal, 0.0))
    apr = max(0.0, _safe_float(apr, 0.0))
    tenure_months = max(1, int(tenure_months or 1))
    r = apr / 12
    if r <= 0:
        emi = principal / tenure_months
    else:
        emi = principal * r * ((1 + r) ** tenure_months) / (((1 + r) ** tenure_months) - 1)

    snap = _financial_snapshot(user_id, supabase)
    new_burn = snap["monthly_burn"] + emi
    new_runway = snap["liquid_nw"] / new_burn if new_burn > 0 else 0.0
    return {
        "emi": emi,
        "new_monthly_burn": new_burn,
        "new_runway_months": new_runway,
        "delta_runway_months": new_runway - snap["runway_months"],
    }


def _compare_tax_regimes_tool(user_id: str, supabase) -> dict:
    fy = current_financial_year()
    ded = get_deductions_summary(user_id, fy, supabase)
    monthly_income, _ = _income_and_regime(user_id, supabase)
    gross_income = monthly_income * 12
    return compare_regimes(
        gross_income,
        {
            "s80c_invested": ded["s80c"]["invested"],
            "s_nps_invested": ded["s_nps"]["invested"],
            "s80d_total": ded["s80d"]["total"],
        },
    )


def _langfuse_client():
    if Langfuse is None:
        return None
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        return Langfuse()
    except Exception:
        return None


def dispatch_tool(name, args, user_id, supabase) -> dict:
    args = args or {}

    def _result():
        if name == "get_financial_snapshot":
            return _financial_snapshot(user_id, supabase)
        if name == "simulate_loan":
            return _simulate_loan(
                user_id,
                supabase,
                principal=args.get("principal", 0.0),
                apr=args.get("apr", 0.0),
                tenure_months=args.get("tenure_months", 1),
            )
        if name == "compare_tax_regimes":
            return _compare_tax_regimes_tool(user_id, supabase)
        if name == "get_capital_gains_summary":
            return get_gains_summary(user_id, current_financial_year(), supabase)
        if name == "get_tax_harvesting_alerts":
            return {"alerts": get_harvesting_alerts(user_id, supabase)}
        if name == "get_insurance_audit":
            return {
                "life": audit_life_cover(user_id, supabase),
                "health": audit_health_cover(user_id, supabase),
                "traps": detect_endowment_traps(user_id, supabase),
            }
        if name == "get_surplus_allocation":
            snap = _financial_snapshot(user_id, supabase)
            return {"plan": allocate_surplus(user_id, snap["surplus"], supabase)}
        if name == "get_80c_gap":
            summary = get_deductions_summary(user_id, current_financial_year(), supabase)
            return {
                "s80c_gap": summary["s80c"]["gap"],
                "nps_gap": summary["s_nps"]["gap"],
                "total_gap": summary["total_gap"],
                "tax_saving_potential": summary["tax_saving_potential"],
            }
        return {"error": f"Unknown tool: {name}"}

    result = _result()
    try:
        supabase.table("ai_tool_calls").insert(
            {
                "user_id": user_id,
                "tool_name": name,
                "arguments": args,
                "result": str(result),
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()
    except Exception:
        # Non-blocking if table does not exist yet.
        pass
    return result


def run_agent_with_trace(
    query: str,
    user_id: str,
    supabase,
    *,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
):
    profile = get_user_profile(user_id, supabase)
    system = SYSTEM.format(**profile)
    messages = [{"role": "user", "content": query}]
    tool_events = []

    lf = _langfuse_client()
    trace = lf.trace(name="wealthos-cfo", user_id=user_id) if lf else None
    span = trace.span(name="agent-loop") if trace else None

    try:
        for _ in range(6):
            resp = call_llm(
                system,
                messages,
                TOOLS,
                api_key=api_key,
                provider=provider,
                model=model,
                max_tokens=2048,
            )
            tool_call = resp.get("tool_call") if isinstance(resp, dict) else None
            if tool_call:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("arguments", {})
                result = dispatch_tool(tool_name, tool_args, user_id, supabase)
                tool_events.append(
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "output": result,
                    }
                )
                if trace:
                    try:
                        trace.event(name=tool_name, input=tool_args, output=str(result))
                    except Exception:
                        pass
                messages.append({"role": "tool", "name": tool_name, "content": str(result)})
            else:
                text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
                return (text or "Analysis incomplete. Try rephrasing.", tool_events)
        return ("Analysis incomplete. Try rephrasing.", tool_events)
    finally:
        if span:
            try:
                span.end()
            except Exception:
                pass


def run_agent(query: str, user_id: str, supabase, **llm_kwargs) -> str:
    text, _ = run_agent_with_trace(query, user_id, supabase, **llm_kwargs)
    return text
