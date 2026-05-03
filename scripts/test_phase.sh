#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/9] Syntax compile checks"
PYTHONPYCACHEPREFIX="$ROOT_DIR/.pycache_tmp" python3 - <<'PY'
import py_compile

files = [
    "app/app.py",
    "app/db.py",
    "app/migrate.py",
    "app/data_providers/amfi.py",
    "app/data_providers/fx.py",
    "app/utils/llm_client.py",
    "app/utils/privacy.py",
    "app/ingestion/ocr_parser.py",
    "app/tax/deductions.py",
    "app/tax/regime_compare.py",
    "app/tax/ca_export.py",
    "app/tax/capital_gains.py",
    "app/insurance/audit.py",
    "scripts/run.py",
]
for f in files:
    py_compile.compile(f, doraise=True)
print("PASS: syntax compilation")
PY

echo "[2/9] LLM client modular tests"
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

echo "[3/9] AMFI + FX provider cache tests"
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

echo "[4/9] Phase wiring contract checks"
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
assert "with tab5:" in app_text
assert "get_deductions_summary" in app_text
assert "compare_regimes" in app_text
assert "generate_ca_export_pdf" in app_text
assert "get_harvesting_alerts" in app_text
assert "Capital Gains" in app_text
assert "tab6" in app_text
assert "Insurance" in app_text
assert "detect_endowment_traps" in app_text

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
    "load_tax_investments",
    "sync_tax_investments",
    "sync_capital_gains",
    "sync_insurance_policies",
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

echo "[5/9] OCR parser + privacy tests"
python3 - <<'PY'
import sys
sys.path.insert(0, ".")

from app.ingestion import ocr_parser

calls = {
    "uploaded": [],
    "removed": [],
    "inserted": [],
    "vision_prompt": "",
}

def fake_sanitise(text):
    return "SANITISED"

def fake_call_vision(prompt, image_bytes, **kwargs):
    calls["vision_prompt"] = prompt
    assert kwargs.get("provider") == "openai"
    return '[{"merchant":"Cafe","amount":150.0,"date":"2026-01-02","currency":"INR","category":"food"}]'

class StorageBucket:
    def upload(self, path, data):
        calls["uploaded"].append(path)
    def remove(self, paths):
        calls["removed"].extend(paths)

class StorageAPI:
    def from_(self, _bucket):
        return StorageBucket()

class TableAPI:
    def insert(self, rows):
        calls["inserted"].extend(rows if isinstance(rows, list) else [rows])
        return self
    def execute(self):
        return None

class SupabaseStub:
    def __init__(self):
        self.storage = StorageAPI()
    def table(self, _name):
        return TableAPI()

sb = SupabaseStub()

orig_sanitise = ocr_parser.sanitise_for_ai
orig_call_vision = ocr_parser.call_vision
ocr_parser.sanitise_for_ai = fake_sanitise
ocr_parser.call_vision = fake_call_vision
try:
    parsed = ocr_parser.parse_file(
        file_bytes=b"txn 9876543210 ABCDE1234F",
        mime_type="image/jpeg",
        user_id="u1",
        supabase=sb,
    )
    assert len(parsed) == 1
    assert parsed[0]["merchant"] == "Cafe"
    assert "SANITISED" in calls["vision_prompt"]
    assert calls["uploaded"] and calls["removed"], "Storage upload/remove should both happen"

    saved = ocr_parser.confirm_and_save(parsed, "u1", sb)
    assert saved == 1
    assert calls["inserted"][0]["source"] == "ocr"
finally:
    ocr_parser.sanitise_for_ai = orig_sanitise
    ocr_parser.call_vision = orig_call_vision

print("PASS: OCR parser privacy + zero-retention flow")
PY

echo "[6/9] Tax module tests"
python3 - <<'PY'
from app.tax.deductions import get_deductions_summary
from app.tax.regime_compare import calc_tax, compare_regimes
from app.tax.ca_export import generate_ca_export_pdf

class Result:
    def __init__(self, data):
        self.data = data

class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}
    def select(self, *_):
        return self
    def eq(self, key, val):
        self.filters[key] = val
        return self
    def execute(self):
        data = [r for r in self.rows if all(r.get(k) == v for k, v in self.filters.items())]
        return Result(data)

class SupabaseStub:
    def __init__(self):
        self.tax_rows = [
            {"user_id": "u1", "financial_year": "2025-2026", "instrument_type": "epf", "amount_invested": 100000},
            {"user_id": "u1", "financial_year": "2025-2026", "instrument_type": "nps_80ccd1b", "amount_invested": 20000},
            {"user_id": "u1", "financial_year": "2025-2026", "instrument_type": "health_insurance_self", "amount_invested": 15000},
        ]
        self.insurance_rows = [
            {"user_id": "u1", "policy_type": "term_life", "annual_premium": 12000, "is_active": True},
        ]
    def table(self, name):
        if name == "tax_investments":
            return Query(self.tax_rows)
        if name == "insurance_policies":
            return Query(self.insurance_rows)
        raise AssertionError(f"Unexpected table {name}")

sb = SupabaseStub()
summary = get_deductions_summary("u1", "2025-2026", sb)
assert summary["s80c"]["invested"] == 112000
assert summary["s_nps"]["invested"] == 20000
assert summary["s80d"]["self"] == 15000
assert summary["s80c"]["gap"] == 38000

assert round(calc_tax(500000, [(250000, 0), (500000, 0.05), (float("inf"), 0.30)]), 2) == 13000.0
cmp = compare_regimes(1500000, {"s80c_invested": 150000, "s_nps_invested": 50000, "s80d_total": 25000})
assert cmp["recommended"] in {"old", "new"}
assert cmp["saving"] >= 0

pdf = generate_ca_export_pdf(
    fy="2025-2026",
    user="user@example.com",
    deductions_df=__import__("pandas").DataFrame(
        [{"Instrument Type": "epf", "Amount Invested": 100000, "Notes": ""}]
    ),
    summary=summary,
    regime_result=cmp,
)
assert isinstance(pdf, (bytes, bytearray)) and len(pdf) > 100
print("PASS: tax modules")
PY

echo "[7/9] Capital gains module tests"
python3 - <<'PY'
import app.tax.capital_gains as cg

class Result:
    def __init__(self, data):
        self.data = data

class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}
    def select(self, *_):
        return self
    def eq(self, key, val):
        self.filters[key] = val
        return self
    def execute(self):
        data = [r for r in self.rows if all(r.get(k) == v for k, v in self.filters.items())]
        return Result(data)

class SupabaseStub:
    def __init__(self):
        self.rows = [
            {"user_id": "u1", "asset_name": "12345", "asset_type": "equity_mf", "buy_date": "2024-01-01", "buy_price": 100, "sell_date": "2025-05-01", "sell_price": 140, "units": 100},
            {"user_id": "u1", "asset_name": "ABC", "asset_type": "stock", "buy_date": "2025-01-01", "buy_price": 200, "sell_date": "2025-06-01", "sell_price": 220, "units": 50},
            {"user_id": "u1", "asset_name": "12345", "asset_type": "equity_mf", "buy_date": "2025-03-01", "buy_price": 130, "sell_date": None, "sell_price": None, "units": 100},
        ]
    def table(self, name):
        assert name == "capital_gains"
        return Query(self.rows)

sb = SupabaseStub()
orig_get_nav = cg.get_nav
cg.get_nav = lambda scheme_code, supabase: {"scheme_code": str(scheme_code), "nav": 120.0, "nav_date": "2026-01-01"}
try:
    assert cg.classify("stock", "2024-01-01", "2025-02-01") == "LTCG"
    summary = cg.get_gains_summary("u1", "2025-2026", sb)
    assert "total_tax" in summary and summary["total_tax"] >= 0
    unrealised = cg.get_unrealised("u1", sb)
    assert unrealised and unrealised[0]["asset_name"] == "12345"
    alerts = cg.get_harvesting_alerts("u1", sb)
    assert isinstance(alerts, list)
finally:
    cg.get_nav = orig_get_nav

print("PASS: capital gains module")
PY

echo "[8/9] Insurance audit module tests"
python3 - <<'PY'
from app.insurance.audit import audit_life_cover, audit_health_cover, detect_endowment_traps

class Result:
    def __init__(self, data):
        self.data = data

class Query:
    def __init__(self, table, rows):
        self.table = table
        self.rows = rows
        self.filters = {}
        self._limit = None
    def select(self, *_):
        return self
    def eq(self, key, val):
        self.filters[key] = val
        return self
    def limit(self, n):
        self._limit = n
        return self
    def execute(self):
        data = [r for r in self.rows if all(r.get(k) == v for k, v in self.filters.items())]
        if self._limit is not None:
            data = data[:self._limit]
        return Result(data)

class SupabaseStub:
    def __init__(self):
        self.insurance = [
            {
                "user_id": "u1", "policy_name": "Term A", "policy_type": "term_life",
                "annual_premium": 12000, "sum_assured": 5000000, "is_active": True,
                "start_date": "2024-01-01", "maturity_date": "2044-01-01", "maturity_value": 0
            },
            {
                "user_id": "u1", "policy_name": "ULIP X", "policy_type": "ulip",
                "annual_premium": 50000, "sum_assured": 300000, "is_active": True,
                "start_date": "2024-01-01", "maturity_date": "2034-01-01", "maturity_value": 350000
            },
            {
                "user_id": "u1", "policy_name": "Health A", "policy_type": "health",
                "annual_premium": 18000, "sum_assured": 800000, "is_active": True,
                "start_date": "2024-01-01", "maturity_date": None, "maturity_value": 0
            },
        ]
        self.profile = [{"user_id": "u1", "monthly_income": 100000}]
    def table(self, name):
        if name == "insurance_policies":
            return Query(name, self.insurance)
        if name == "user_profile":
            return Query(name, self.profile)
        raise AssertionError(f"Unexpected table {name}")

sb = SupabaseStub()
life = audit_life_cover("u1", sb)
health = audit_health_cover("u1", sb)
traps = detect_endowment_traps("u1", sb)

assert life["recommended"] == 12000000
assert life["actual"] == 5000000
assert life["adequacy"] == "underinsured"
assert health["actual"] == 800000
assert health["adequacy"] == "underinsured"
assert traps and traps[0]["policy_name"] == "ULIP X"
print("PASS: insurance audit module")
PY

echo "[9/9] Quick streamlit route check (already-running app preferred)"
if command -v curl >/dev/null 2>&1; then
  if curl -sS -o /tmp/wealthos_health.html -w "%{http_code}" "http://127.0.0.1:8514" | grep -q "200"; then
    echo "PASS: streamlit reachable at http://127.0.0.1:8514"
  else
    echo "WARN: streamlit not detected on :8514 (start app manually for UI smoke check)"
  fi
fi

echo "All phase tests completed."
