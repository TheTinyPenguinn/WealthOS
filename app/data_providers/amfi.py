from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import urllib.request

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
STALE_HOURS = 6


def _parse_timestamp(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_cache_stale(latest_ts: str, stale_hours: int) -> bool:
    parsed = _parse_timestamp(latest_ts)
    if parsed is None:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > timedelta(hours=stale_hours)


def _split_line(line: str) -> list[str]:
    # AMFI has historically published semicolon-separated rows; some mirrors use pipes.
    if "|" in line:
        return [p.strip() for p in line.split("|")]
    return [p.strip() for p in line.split(";")]


def fetch_and_cache_navs(supabase) -> Dict[str, dict]:
    """
    Fetch AMFI NAV feed and cache rows in mf_nav_cache.
    Returns {scheme_code: {"nav": float, "nav_date": str}}.
    """
    latest = (
        supabase.table("mf_nav_cache")
        .select("fetched_at")
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    if latest.data and not _is_cache_stale(latest.data[0].get("fetched_at"), STALE_HOURS):
        rows = supabase.table("mf_nav_cache").select("scheme_code, nav, nav_date").execute()
        return {
            str(r["scheme_code"]): {"nav": float(r["nav"]), "nav_date": str(r["nav_date"])}
            for r in (rows.data or [])
            if r.get("scheme_code") is not None and r.get("nav") is not None
        }

    with urllib.request.urlopen(AMFI_URL, timeout=20) as resp:
        payload = resp.read().decode("utf-8", errors="ignore")

    nav_map: Dict[str, dict] = {}
    upserts = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("scheme code"):
            continue

        parts = _split_line(line)
        if len(parts) < 6:
            continue

        scheme_code = parts[0]
        nav_str = parts[-2]
        nav_date = parts[-1]
        if not scheme_code or not nav_str:
            continue

        try:
            nav_val = float(nav_str)
        except Exception:
            continue

        nav_map[scheme_code] = {"nav": nav_val, "nav_date": nav_date}
        upserts.append(
            {
                "scheme_code": scheme_code,
                "nav": nav_val,
                "nav_date": nav_date,
                "fetched_at": now_iso,
            }
        )

    for i in range(0, len(upserts), 500):
        supabase.table("mf_nav_cache").upsert(upserts[i : i + 500], on_conflict="scheme_code").execute()

    return nav_map


def get_nav(scheme_code: str, supabase) -> Optional[dict]:
    """
    Return {"scheme_code", "nav", "nav_date"} for one scheme, or None.
    Refreshes cache if stale or missing.
    """
    if not scheme_code:
        return None
    code = str(scheme_code).strip()

    row = (
        supabase.table("mf_nav_cache")
        .select("scheme_code, nav, nav_date, fetched_at")
        .eq("scheme_code", code)
        .limit(1)
        .execute()
    )

    if row.data:
        cached = row.data[0]
        if not _is_cache_stale(cached.get("fetched_at"), STALE_HOURS):
            return {
                "scheme_code": str(cached["scheme_code"]),
                "nav": float(cached["nav"]),
                "nav_date": str(cached["nav_date"]),
            }

    all_navs = fetch_and_cache_navs(supabase)
    hit = all_navs.get(code)
    if not hit:
        return None
    return {"scheme_code": code, "nav": float(hit["nav"]), "nav_date": str(hit["nav_date"])}
