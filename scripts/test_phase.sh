#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/5] Syntax compile checks"
PYTHONPYCACHEPREFIX="$ROOT_DIR/.pycache_tmp" python3 - <<'PY'
import py_compile

files = [
    "app/app.py",
    "app/db.py",
    "app/migrate.py",
    "app/data_providers/amfi.py",
    "app/data_providers/fx.py",
    "app/utils/llm_client.py",
    "scripts/run.py",
]
for f in files:
    py_compile.compile(f, doraise=True)
print("PASS: syntax compilation")
PY

echo "[2/5] LLM client modular tests"
python3 - <<'PY'
import os
import importlib.util

spec = importlib.util.spec_from_file_location("llm_client", "app/utils/llm_client.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "k-openai"
os.environ["GEMINI_API_KEY"] = "k-gemini"
os.environ["ANTHROPIC_API_KEY"] = "k-anthropic"

assert mod._normalize_provider(None) == "openai"
assert mod._normalize_provider("bad-provider") == "gemini"
assert mod._resolve_api_key("openai", None) == "k-openai"
assert mod._resolve_api_key("gemini", "manual-key") == "manual-key"
print("PASS: llm_client behavior")
PY

echo "[3/5] AMFI + FX provider cache tests"
python3 - <<'PY'
import io
import json
import importlib.util
import urllib.request

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

amfi = load_module("app/data_providers/amfi.py", "amfi")
fx = load_module("app/data_providers/fx.py", "fx")

class Result:
    def __init__(self, data):
        self.data = data

class Query:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.rows = store.setdefault(table, [])
        self._eq = None
        self._limit = None
        self._order = None
        self._desc = False

    def select(self, *_):
        return self

    def order(self, key, desc=False):
        self._order = key
        self._desc = bool(desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def eq(self, key, val):
        self._eq = (key, val)
        return self

    def insert(self, payload):
        if isinstance(payload, dict):
            payload = [payload]
        self.rows.extend(payload)
        return self

    def upsert(self, payload, on_conflict=None):
        if isinstance(payload, dict):
            payload = [payload]
        for p in payload:
            if on_conflict:
                found = False
                for r in self.rows:
                    if r.get(on_conflict) == p.get(on_conflict):
                        r.update(p)
                        found = True
                        break
                if not found:
                    self.rows.append(dict(p))
            else:
                self.rows.append(dict(p))
        return self

    def execute(self):
        data = list(self.rows)
        if self._eq:
            k, v = self._eq
            data = [r for r in data if r.get(k) == v]
        if self._order:
            data.sort(key=lambda r: r.get(self._order, ""), reverse=self._desc)
        if self._limit is not None:
            data = data[: self._limit]
        return Result(data)

class SupabaseStub:
    def __init__(self):
        self.store = {}
    def table(self, name):
        return Query(name, self.store)

sb = SupabaseStub()
orig_urlopen = urllib.request.urlopen
calls = {"amfi": 0, "fx": 0}

def fake_urlopen(url, timeout=0):
    if "amfiindia" in url:
        calls["amfi"] += 1
        payload = (
            "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
            "12345;INF000000001;;;Sample Fund;12.34;01-Jan-2026\n"
        )
        return io.BytesIO(payload.encode("utf-8"))
    if "frankfurter" in url:
        calls["fx"] += 1
        return io.BytesIO(json.dumps({"rates": {"INR": 83.25}}).encode("utf-8"))
    return orig_urlopen(url, timeout=timeout)

urllib.request.urlopen = fake_urlopen
try:
    nav_map = amfi.fetch_and_cache_navs(sb)
    assert "12345" in nav_map
    nav = amfi.get_nav("12345", sb)
    assert nav and abs(nav["nav"] - 12.34) < 1e-9
    # Fresh cache should avoid a second network hit.
    amfi.fetch_and_cache_navs(sb)
    assert calls["amfi"] == 1

    r1 = fx.get_usd_inr(sb)
    r2 = fx.get_usd_inr(sb)
    assert abs(r1 - 83.25) < 1e-9 and abs(r2 - 83.25) < 1e-9
    assert calls["fx"] == 1
    assert abs(fx.rsu_inr_value(10, 2, sb) - 1665.0) < 1e-9
finally:
    urllib.request.urlopen = orig_urlopen

print("PASS: amfi/fx caching and conversion")
PY

echo "[4/5] Phase wiring contract checks"
python3 - <<'PY'
from pathlib import Path

app_text = Path("app/app.py").read_text(encoding="utf-8")
db_text = Path("app/db.py").read_text(encoding="utf-8")
env_text = Path(".env.example").read_text(encoding="utf-8")

# Phase 1+2 contracts in app.
assert "call_llm(" in app_text
assert "profile_risk_details" in app_text
assert "system_prompt=risk_system_prompt" in app_text
assert "plot_runway_impact(liquid_net_worth" in app_text
assert "st.session_state.illiquid_assets" in app_text
assert "st.session_state.credit_cards" in app_text

# Ensure no direct model SDK usage in app.py.
for forbidden in ("google.generativeai", "GenerativeModel("):
    assert forbidden not in app_text, f"Forbidden direct AI call found: {forbidden}"

# DB support for new modules.
for required in (
    "sync_illiquid_assets",
    "sync_credit_cards",
    "upsert_user_profile",
    "illiquid_assets",
    "credit_cards",
    "user_profile",
):
    assert required in db_text, f"Missing db support: {required}"

# Env contract keys.
for key in (
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "LLM_PROVIDER",
):
    assert key in env_text, f"Missing env key in template: {key}"

print("PASS: phase contract wiring")
PY

echo "[5/5] Quick streamlit route check (already-running app preferred)"
if command -v curl >/dev/null 2>&1; then
  if curl -sS -o /tmp/wealthos_health.html -w "%{http_code}" "http://127.0.0.1:8514" | grep -q "200"; then
    echo "PASS: streamlit reachable at http://127.0.0.1:8514"
  else
    echo "WARN: streamlit not detected on :8514 (start app manually for UI smoke check)"
  fi
fi

echo "All phase tests completed."
