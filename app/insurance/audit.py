from __future__ import annotations

from datetime import datetime


def _safe_float(value):
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _active_policies(user_id, supabase):
    res = supabase.table("insurance_policies").select("*").eq("user_id", user_id).eq("is_active", True).execute()
    return res.data or []


def audit_life_cover(user_id, supabase) -> dict:
    policies = _active_policies(user_id, supabase)
    profile_res = supabase.table("user_profile").select("monthly_income").eq("user_id", user_id).limit(1).execute()
    monthly_income = 0.0
    if profile_res.data:
        monthly_income = _safe_float(profile_res.data[0].get("monthly_income"))

    recommended = monthly_income * 12 * 10  # 10x annual income
    actual = sum(_safe_float(p.get("sum_assured")) for p in policies if p.get("policy_type") == "term_life")
    gap = max(0.0, recommended - actual)
    adequacy = "adequate" if recommended <= 0 or actual >= recommended else "underinsured"
    return {"recommended": recommended, "actual": actual, "gap": gap, "adequacy": adequacy}


def audit_health_cover(user_id, supabase) -> dict:
    policies = _active_policies(user_id, supabase)
    recommended = 1_000_000.0
    actual = sum(_safe_float(p.get("sum_assured")) for p in policies if p.get("policy_type") == "health")
    gap = max(0.0, recommended - actual)
    adequacy = "adequate" if actual >= recommended else "underinsured"
    return {"recommended": recommended, "actual": actual, "gap": gap, "adequacy": adequacy}


def _years_between(start_date, end_date):
    try:
        s = datetime.fromisoformat(str(start_date)).date()
        e = datetime.fromisoformat(str(end_date)).date()
        years = max(1, int((e - s).days / 365.25))
        return years
    except Exception:
        return 1


def detect_endowment_traps(user_id, supabase) -> list[dict]:
    policies = _active_policies(user_id, supabase)
    trap_types = {"endowment", "money_back", "ulip"}
    flagged = []

    for p in policies:
        if p.get("policy_type") not in trap_types:
            continue
        annual_premium = _safe_float(p.get("annual_premium"))
        maturity_value = _safe_float(p.get("maturity_value"))
        years = _years_between(p.get("start_date"), p.get("maturity_date"))
        if annual_premium <= 0 or maturity_value <= 0 or years <= 0:
            continue

        total_paid = annual_premium * years
        if total_paid <= 0:
            continue

        estimated_irr = (maturity_value / total_paid) ** (1 / years) - 1
        if estimated_irr < 0.07:
            surrender_value = total_paid * 0.30
            elss_projection = annual_premium * (((1 + 0.12) ** years - 1) / 0.12)
            flagged.append(
                {
                    "policy_name": p.get("policy_name", "Unknown Policy"),
                    "estimated_irr": estimated_irr,
                    "surrender_value": surrender_value,
                    "elss_projection": elss_projection,
                    "annual_premium": annual_premium,
                }
            )

    return flagged
