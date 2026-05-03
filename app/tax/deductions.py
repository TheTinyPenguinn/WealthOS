from __future__ import annotations

from datetime import datetime

LIMIT_80C = 150_000
LIMIT_NPS = 50_000
LIMIT_80D_SELF = 25_000
LIMIT_80D_PARENTS = 50_000


def current_financial_year() -> str:
    now = datetime.now()
    if now.month >= 4:
        return f"{now.year}-{now.year + 1}"
    return f"{now.year - 1}-{now.year}"


def _sum_by_types(rows, allowed_types):
    total = 0.0
    for row in rows:
        if row.get("instrument_type") in allowed_types:
            total += float(row.get("amount_invested", 0.0) or 0.0)
    return total


def get_deductions_summary(user_id, fy, supabase) -> dict:
    res = (
        supabase.table("tax_investments")
        .select("*")
        .eq("user_id", user_id)
        .eq("financial_year", fy)
        .execute()
    )
    rows = res.data or []

    s80c_types = {
        "epf",
        "ppf",
        "elss",
        "nsc",
        "tax_saver_fd",
        "life_insurance_premium",
        "home_loan_principal",
        "other_80c",
    }
    s80c_invested = _sum_by_types(rows, s80c_types)
    nps_invested = _sum_by_types(rows, {"nps_80ccd1b"})
    s80d_self = _sum_by_types(rows, {"health_insurance_self"})
    s80d_parents = _sum_by_types(rows, {"health_insurance_parents"})

    # Insurance premiums (active policies) should feed 80C tracker.
    ins_res = supabase.table("insurance_policies").select("*").eq("user_id", user_id).eq("is_active", True).execute()
    ins_rows = ins_res.data or []
    life_policy_types = {"term_life", "endowment", "money_back", "ulip"}
    insurance_80c = sum(
        float(r.get("annual_premium", 0.0) or 0.0)
        for r in ins_rows
        if r.get("policy_type") in life_policy_types
    )
    s80c_invested += insurance_80c

    s80c_gap = max(0.0, LIMIT_80C - min(s80c_invested, LIMIT_80C))
    nps_gap = max(0.0, LIMIT_NPS - min(nps_invested, LIMIT_NPS))
    s80d_total = min(s80d_self, LIMIT_80D_SELF) + min(s80d_parents, LIMIT_80D_PARENTS)
    total_gap = s80c_gap + nps_gap
    tax_saving_potential = total_gap * 0.30 * 1.04

    return {
        "s80c": {"invested": s80c_invested, "limit": LIMIT_80C, "gap": s80c_gap},
        "s_nps": {"invested": nps_invested, "limit": LIMIT_NPS, "gap": nps_gap},
        "s80d": {
            "self": min(s80d_self, LIMIT_80D_SELF),
            "parents": min(s80d_parents, LIMIT_80D_PARENTS),
            "total": s80d_total,
        },
        "total_gap": total_gap,
        "tax_saving_potential": tax_saving_potential,
    }


def get_80c_alert(user_id, supabase) -> str | None:
    now = datetime.now()
    if now.month not in (1, 2, 3):
        return None

    fy = current_financial_year()
    summary = get_deductions_summary(user_id, fy, supabase)
    gap = float(summary["s80c"]["gap"])
    if gap > 10_000:
        return f"80C gap is Rs {gap:,.0f}. You still have time this FY to optimize tax."
    return None
