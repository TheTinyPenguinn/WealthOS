from __future__ import annotations

from datetime import date, datetime

from ai.agent import get_financial_snapshot
from app.tax.deductions import current_financial_year, get_deductions_summary


def current_fy() -> str:
    return current_financial_year()


def today() -> str:
    return date.today().isoformat()


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def get_coverage_scores(user_id: str, supabase) -> dict:
    try:
        profile_res = supabase.table("user_profile").select("monthly_income").eq("user_id", user_id).limit(1).execute()
        profile = profile_res.data[0] if profile_res.data else {}
    except Exception:
        profile = {}
    monthly_income = _safe_float(profile.get("monthly_income"), 0.0)
    life_recommended = monthly_income * 12 * 10
    health_recommended = 1_000_000.0

    try:
        policies_res = (
            supabase.table("insurance_policies")
            .select("*")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .execute()
        )
        rows = policies_res.data or []
    except Exception:
        rows = []

    life_actual = sum(_safe_float(r.get("sum_assured"), 0.0) for r in rows if r.get("policy_type") == "term_life")
    health_actual = sum(_safe_float(r.get("sum_assured"), 0.0) for r in rows if r.get("policy_type") == "health")
    life_score = 1.0 if life_recommended <= 0 else min(life_actual / life_recommended, 1.0)
    health_score = min(health_actual / health_recommended, 1.0)
    return {
        "life_score": life_score,
        "health_score": health_score,
        "overall_score": (life_score + health_score) / 2.0,
    }


def get_goal_on_track_pct(user_id: str, supabase) -> float:
    try:
        goals_res = supabase.table("goals").select("*").eq("user_id", user_id).execute()
        goals = goals_res.data or []
    except Exception:
        goals = []
    if not goals:
        return 0.0

    now = datetime.now().date()
    on_track = 0
    considered = 0
    for g in goals:
        try:
            target_date = datetime.fromisoformat(str(g.get("target_date"))).date()
        except Exception:
            continue
        target_amount = _safe_float(g.get("target_amount"), 0.0)
        current_amount = _safe_float(g.get("current_amount"), 0.0)
        if target_amount <= 0:
            continue
        considered += 1
        days_left = max(1, (target_date - now).days)
        monthly_needed = (target_amount - current_amount) / max(1.0, days_left / 30.0)
        if monthly_needed <= 0:
            on_track += 1
            continue
        progress_pct = current_amount / target_amount
        if progress_pct >= 0.5 or monthly_needed <= 0.1 * target_amount:
            on_track += 1

    if considered == 0:
        return 0.0
    return min(max(on_track / considered, 0.0), 1.0)


def calculate_freedom_score(user_id: str, supabase) -> dict:
    snap = get_financial_snapshot(user_id, supabase)
    try:
        tax = get_deductions_summary(user_id, current_fy(), supabase)
    except Exception:
        tax = {
            "s80c": {"invested": 0.0, "limit": 150000.0, "gap": 150000.0},
            "s_nps": {"invested": 0.0, "limit": 50000.0, "gap": 50000.0},
            "s80d": {"self": 0.0, "parents": 0.0, "total": 0.0},
            "total_gap": 275000.0,
            "tax_saving_potential": 0.0,
        }
    insurance = get_coverage_scores(user_id, supabase)
    goal_pct = get_goal_on_track_pct(user_id, supabase)

    monthly_income = max(_safe_float(snap.get("monthly_income"), 0.0), 1.0)
    savings_rate = _safe_float(snap.get("monthly_savings"), 0.0) / monthly_income
    debt_ratio = _safe_float(snap.get("high_apr_emi"), 0.0) / monthly_income
    runway = _safe_float(snap.get("runway_months"), 0.0)
    tax_eff = 1.0 - (_safe_float(tax.get("total_gap"), 0.0) / 275_000.0)

    score = int(
        min(savings_rate / 0.30, 1.0) * 250
        + max(0.0, 1.0 - debt_ratio) * 200
        + min(runway / 12.0, 1.0) * 200
        + max(0.0, tax_eff) * 150
        + min(max(_safe_float(insurance.get("overall_score"), 0.0), 0.0), 1.0) * 100
        + min(max(goal_pct, 0.0), 1.0) * 100
    )
    score = max(0, min(score, 1000))

    tiers = [(800, "Sovereign"), (600, "Free"), (400, "Building"), (200, "Stable"), (0, "Trapped")]
    tier = next(t for threshold, t in tiers if score >= threshold)

    try:
        supabase.table("score_history").upsert(
            {
                "user_id": user_id,
                "date": today(),
                "score": score,
                "tier": tier,
            },
            on_conflict="user_id,date",
        ).execute()
    except Exception:
        pass

    return {
        "total_score": score,
        "tier": tier,
        "breakdown": {
            "savings": int(min(savings_rate / 0.30, 1.0) * 250),
            "debt_freedom": int(max(0.0, 1.0 - debt_ratio) * 200),
            "runway": int(min(runway / 12.0, 1.0) * 200),
            "tax_efficiency": int(max(0.0, tax_eff) * 150),
            "insurance": int(min(max(_safe_float(insurance.get("overall_score"), 0.0), 0.0), 1.0) * 100),
            "goals": int(min(max(goal_pct, 0.0), 1.0) * 100),
        },
        "inputs": {
            "savings_rate": savings_rate,
            "debt_ratio": debt_ratio,
            "runway_months": runway,
            "tax_efficiency": tax_eff,
            "goal_pct": goal_pct,
            "insurance_overall": insurance.get("overall_score", 0.0),
        },
    }
