from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def today() -> date:
    return date.today()


def _safe_float(val, default=0.0):
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def fetch_ef(user_id, supabase) -> dict:
    try:
        res = supabase.table("emergency_fund").select("*").eq("user_id", user_id).limit(1).execute()
    except Exception:
        return {"target_months": 6, "current_amount": 0.0, "account_name": ""}
    if not res.data:
        return {"target_months": 6, "current_amount": 0.0, "account_name": ""}
    row = res.data[0]
    return {
        "target_months": int(row.get("target_months") or 6),
        "current_amount": _safe_float(row.get("current_amount"), 0.0),
        "account_name": row.get("account_name", ""),
    }


def get_monthly_burn(user_id, supabase) -> float:
    monthly_floor = 0.0
    try:
        fixed_rows = supabase.table("fixed_costs").select("*").eq("user_id", user_id).execute().data or []
    except Exception:
        fixed_rows = []
    for row in fixed_rows:
        freq = str(row.get("frequency", "Monthly"))
        amount = _safe_float(row.get("amount"), 0.0)
        if freq == "Monthly":
            monthly_floor += amount
        elif freq == "Quarterly":
            monthly_floor += amount / 3
        elif freq == "Half-Yearly":
            monthly_floor += amount / 6
        elif freq == "Yearly":
            monthly_floor += amount / 12

    try:
        obligations = supabase.table("obligations").select("*").eq("user_id", user_id).execute().data or []
    except Exception:
        obligations = []
    monthly_emi = sum(_safe_float(r.get("monthly_emi"), 0.0) for r in obligations)

    try:
        expenses = supabase.table("expenses").select("*").eq("user_id", user_id).execute().data or []
    except Exception:
        expenses = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    variable = 0.0
    for row in expenses:
        d = row.get("date")
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff or dt > now:
            continue
        if str(row.get("category", "")).lower() in {"needs", "wants"}:
            variable += abs(_safe_float(row.get("amount"), 0.0))

    return monthly_floor + monthly_emi + variable


def get_ef_status(user_id, supabase) -> dict:
    ef = fetch_ef(user_id, supabase)
    burn = get_monthly_burn(user_id, supabase)
    covered = ef["current_amount"] / burn if burn > 0 else 0.0
    status = "strong" if covered >= 6 else "adequate" if covered >= 3 else "building"
    target = burn * ef["target_months"]
    return {
        "target": target,
        "current": ef["current_amount"],
        "months_covered": covered,
        "status": status,
        "gap": max(0.0, target - ef["current_amount"]),
    }


def get_active_goals(user_id, supabase):
    try:
        res = (
            supabase.table("goals")
            .select("*")
            .eq("user_id", user_id)
            .order("priority")
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def get_high_apr_balance(user_id, supabase) -> float:
    try:
        obligations = supabase.table("obligations").select("*").eq("user_id", user_id).execute().data or []
    except Exception:
        obligations = []
    high_apr = 0.0
    for row in obligations:
        rate = _safe_float(row.get("interest_rate"), 0.0)
        if rate > 12:
            high_apr += max(0.0, _safe_float(row.get("current_balance"), 0.0))
    return high_apr


def allocate_surplus(user_id, monthly_surplus, supabase) -> list[dict]:
    ef = get_ef_status(user_id, supabase)
    goals = get_active_goals(user_id, supabase)
    allocs = []
    rem = max(0.0, _safe_float(monthly_surplus, 0.0))

    if rem <= 0:
        return [{"label": "No allocable surplus", "amount": 0.0, "note": "Surplus is zero or negative."}]

    # Gate 1 — Emergency Fund
    if ef["status"] == "building":
        return [
            {
                "label": "Emergency Fund (LOCKED)",
                "amount": rem,
                "note": "EF<3mo — 100% surplus to EF. No investments until adequate.",
            }
        ]

    if ef["status"] == "adequate":
        c = rem * 0.5
        allocs.append({"label": "Emergency Fund top-up", "amount": c})
        rem -= c

    # Gate 2 — High-APR debt
    high_apr = get_high_apr_balance(user_id, supabase)
    if high_apr > 0 and rem > 0:
        kill = min(rem, high_apr)
        allocs.append({"label": "Kill high-APR debt", "amount": kill})
        rem -= kill

    # Remaining — distribute by goal priority
    for g in goals:
        if rem <= 0:
            break
        target_date = g.get("target_date")
        try:
            td = datetime.fromisoformat(str(target_date)).date()
        except Exception:
            td = today()
        months_left = max(1, (td - today()).days / 30)
        needed = max(0.0, (_safe_float(g.get("target_amount"), 0.0) - _safe_float(g.get("current_amount"), 0.0)) / months_left)
        c = min(rem, needed)
        if c > 0:
            allocs.append(
                {
                    "label": g.get("name", "Goal"),
                    "amount": c,
                    "instrument": g.get("recommended_instrument", ""),
                }
            )
            rem -= c

    if rem > 0:
        allocs.append({"label": "Wealth building (equity SIP)", "amount": rem})
    return allocs
