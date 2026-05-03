from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import json
import urllib.request

FX_URL = "https://api.frankfurter.app/latest?from=USD&to=INR"
STALE_HOURS = 24


def _parse_timestamp(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_stale(ts: str, stale_hours: int) -> bool:
    parsed = _parse_timestamp(ts)
    if parsed is None:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > timedelta(hours=stale_hours)


def _fetch_live_fx() -> float:
    with urllib.request.urlopen(FX_URL, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return float(payload["rates"]["INR"])


def get_usd_inr(supabase) -> float:
    cached = (
        supabase.table("fx_rates")
        .select("rate, fetched_at")
        .eq("currency_pair", "USD/INR")
        .limit(1)
        .execute()
    )

    if cached.data:
        row = cached.data[0]
        if not _is_stale(row.get("fetched_at"), STALE_HOURS):
            return float(row["rate"])

    live_rate = _fetch_live_fx()
    supabase.table("fx_rates").upsert(
        {
            "currency_pair": "USD/INR",
            "rate": live_rate,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="currency_pair",
    ).execute()
    return live_rate


def rsu_inr_value(units: float, usd_price: float, supabase) -> float:
    return round(float(units) * float(usd_price) * get_usd_inr(supabase), 2)
