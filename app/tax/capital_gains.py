from __future__ import annotations

from datetime import date, datetime
import re

from app.data_providers.amfi import get_nav
from app.tax.deductions import current_financial_year

HOLD_DAYS = {"equity_mf": 365, "stock": 365, "debt_mf": 1095, "real_estate": 730, "other": 365}
LTCG_EXEMPT = 125_000


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()


def _fy_bounds(fy: str):
    start_year = int(str(fy).split("-")[0])
    start = date(start_year, 4, 1)
    end = date(start_year + 1, 3, 31)
    return start, end


def classify(asset_type, buy_date, sell_date) -> str:
    asset_type = str(asset_type or "other")
    hold_required = HOLD_DAYS.get(asset_type, HOLD_DAYS["other"])
    buy = _to_date(buy_date)
    sell = _to_date(sell_date)
    return "LTCG" if (sell - buy).days >= hold_required else "STCG"


def get_gains_summary(user_id, fy, supabase) -> dict:
    start, end = _fy_bounds(fy)
    res = supabase.table("capital_gains").select("*").eq("user_id", user_id).execute()
    rows = res.data or []

    total_ltcg = 0.0
    total_stcg = 0.0
    equity_ltcg = 0.0
    non_equity_ltcg = 0.0
    realised_rows = []

    for row in rows:
        if row.get("sell_date") in (None, ""):
            continue
        sell_date = _to_date(row["sell_date"])
        if sell_date < start or sell_date > end:
            continue
        buy_date = _to_date(row["buy_date"])
        buy_price = float(row.get("buy_price", 0.0) or 0.0)
        sell_price = float(row.get("sell_price", 0.0) or 0.0)
        units = float(row.get("units", 0.0) or 0.0)
        gain = (sell_price - buy_price) * units
        gain_type = classify(row.get("asset_type"), buy_date, sell_date)
        realised_rows.append({**row, "gain": gain, "gain_type": gain_type})

        if gain_type == "LTCG":
            total_ltcg += gain
            if row.get("asset_type") in {"equity_mf", "stock"}:
                equity_ltcg += gain
            else:
                non_equity_ltcg += gain
        else:
            total_stcg += gain

    taxable_equity_ltcg = max(0.0, equity_ltcg - LTCG_EXEMPT)
    taxable_non_equity_ltcg = max(0.0, non_equity_ltcg)
    taxable_ltcg = taxable_equity_ltcg + taxable_non_equity_ltcg

    ltcg_tax = max(0.0, taxable_ltcg) * 0.125
    stcg_tax = max(0.0, total_stcg) * 0.20
    total_tax = ltcg_tax + stcg_tax

    return {
        "total_ltcg": total_ltcg,
        "taxable_ltcg": taxable_ltcg,
        "ltcg_tax": ltcg_tax,
        "total_stcg": total_stcg,
        "stcg_tax": stcg_tax,
        "total_tax": total_tax,
        "realised_rows": realised_rows,
    }


def _mf_current_price(asset_name: str, supabase):
    raw = str(asset_name or "").strip()
    match = re.search(r"\d+", raw)
    scheme_code = match.group(0) if match else raw
    nav_data = get_nav(scheme_code, supabase)
    if nav_data and nav_data.get("nav") is not None:
        return float(nav_data["nav"])
    return None


def get_unrealised(user_id, supabase) -> list[dict]:
    res = supabase.table("capital_gains").select("*").eq("user_id", user_id).execute()
    rows = res.data or []
    today = date.today()
    out = []

    for row in rows:
        if row.get("sell_date") not in (None, ""):
            continue
        buy_date = _to_date(row["buy_date"])
        asset_type = str(row.get("asset_type", "other"))
        buy_price = float(row.get("buy_price", 0.0) or 0.0)
        units = float(row.get("units", 0.0) or 0.0)
        current_price = buy_price

        if asset_type == "equity_mf":
            fetched = _mf_current_price(str(row.get("asset_name", "")), supabase)
            if fetched is not None and fetched > 0:
                current_price = fetched

        unrealised_gain = (current_price - buy_price) * units
        days_held = max(0, (today - buy_date).days)
        gain_type = classify(asset_type, buy_date, today)
        out.append(
            {
                "asset_name": row.get("asset_name", "Unknown"),
                "asset_type": asset_type,
                "buy_date": buy_date.isoformat(),
                "buy_price": buy_price,
                "current_price": current_price,
                "units": units,
                "unrealised_gain": unrealised_gain,
                "days_held": days_held,
                "gain_type": gain_type,
            }
        )

    return sorted(out, key=lambda x: x["unrealised_gain"])


def get_harvesting_alerts(user_id, supabase) -> list[str]:
    positions = get_unrealised(user_id, supabase)
    summary = get_gains_summary(user_id, current_financial_year(), supabase)
    alerts = []

    for pos in positions:
        if pos["unrealised_gain"] < -5000 and summary["total_stcg"] > 0:
            saving = min(abs(pos["unrealised_gain"]), summary["total_stcg"]) * 0.20
            alerts.append(
                f"Sell {pos['asset_name']}: book Rs {abs(pos['unrealised_gain']):,.0f} "
                f"loss -> offset STCG -> saves Rs {saving:,.0f} tax"
            )

        days_left = HOLD_DAYS.get(pos["asset_type"], HOLD_DAYS["other"]) - pos["days_held"]
        if 0 < days_left <= 45 and pos["unrealised_gain"] > 10000:
            saving = pos["unrealised_gain"] * (0.20 - 0.125)
            if saving > 2000:
                alerts.append(
                    f"Hold {pos['asset_name']} {days_left} more days -> "
                    f"STCG to LTCG -> saves Rs {saving:,.0f}"
                )

    return alerts
