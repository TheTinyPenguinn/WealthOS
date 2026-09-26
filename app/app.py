"""
WealthOS: Personal Finance Dashboard
Tabbed layout with Investment Tracking, True Net Worth calculation, Zerodha Integration,
and Asset/Liability tracking.
"""

import sys
import types
from pathlib import Path

# Ensure package-style imports like `from app...` resolve correctly when running
# `streamlit run app/app.py` from project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Streamlit can load this file in a way that binds `app` to this module, which
# breaks imports like `from app.data_providers...`. Force-register `app` as a
# package pointing to the app directory.
existing_app = sys.modules.get("app")
if existing_app is not None and not hasattr(existing_app, "__path__"):
    # Streamlit has bound `app` to this script rather than the package. Drop it —
    # and drop every submodule imported against it, because they hold a reference
    # to the old parent. Leaving them behind breaks a redeploy two ways: the next
    # `from app...` import raises KeyError mid-reload, and the stale modules keep
    # serving the previous deploy's code even though the files on disk are new.
    for stale in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        del sys.modules[stale]
if "app" not in sys.modules:
    pkg = types.ModuleType("app")
    pkg.__path__ = [str(APP_DIR)]  # namespace package path
    sys.modules["app"] = pkg

import streamlit as st
import pandas as pd
import numpy as np
import os
import shutil
import json
from datetime import date, datetime
import certifi
import db  # Supabase integration
from app.data_providers.amfi import get_nav
from app.data_providers.fx import get_usd_inr
from app.utils.llm_client import call_llm
from app.utils.bank_statement_csv import parse_bank_statement_csv_from_bytes
from app.ingestion.ocr_parser import parse_file, confirm_and_save
from app.tax.deductions import get_deductions_summary, get_80c_alert, current_financial_year
from app.tax.regime_compare import compare_regimes
from app.tax.capital_gains import get_harvesting_alerts
from app.insurance.audit import audit_life_cover, audit_health_cover, detect_endowment_traps
from app.goals.sequencer import get_ef_status, allocate_surplus
from app.scoring.freedom_score import calculate_freedom_score
from ai.agent import run_agent, run_agent_with_trace

# Fix SSL certificate issues for yfinance on Mac
os.environ['SSL_CERT_FILE'] = certifi.where()

# Optional yfinance import
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    yf = None

# Optional openpyxl import for Excel support
try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

def _get_secret_or_env(key, default=""):
    env_value = str(os.getenv(key, default)).strip()
    if env_value:
        return env_value
    try:
        return str(st.secrets.get(key, default)).strip()
    except Exception:
        # Allow running without secrets.toml by falling back to environment variables.
        return str(default).strip()


def _resolved_llm_provider() -> str:
    """Single source of truth for chat/agent provider (env, secrets, then safe default)."""
    p = _get_secret_or_env("LLM_PROVIDER", "gemini").strip().lower() or "gemini"
    if p not in ("gemini", "openai", "anthropic"):
        return "gemini"
    return p


def _llm_runtime_kwargs() -> dict:
    """API key from session (optional); provider from env; model from session."""
    key = st.session_state.get("api_key")
    return {
        "api_key": key if key else None,
        "provider": _resolved_llm_provider(),
        "model": st.session_state.get("selected_model"),
    }

# ============================================================================
# GLOBAL HELPER: LIVE CURRENCY
# ============================================================================

@st.cache_data(ttl=3600)  # 1 hour cache
def get_usd_rate():
    """Get live USD to INR exchange rate with fallback."""
    try:
        return float(get_usd_inr(db.supabase))
    except Exception:
        pass
    return 87.5  # Fallback rate

# Optional Plotly import for charts
try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    go = None

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

CSV_FILE = "expenses.csv"
INVESTMENTS_FILE = "investments.csv"
BACKUP_DIR = "backups"
CATEGORIES = ["Needs", "Wants", "Financial", "Income", "Asset", "One-Time"] # Added "One-Time"
ASSET_TYPES = ["Stock", "Mutual Fund", "Gold", "ETF", "Crypto"]
HEADER_KEYWORDS = ["date", "txn date", "description", "narration", "credit", "debit", 
                   "withdrawal", "deposit", "amount", "particulars", "remarks"]

# Auto-Categorization Rules
KEYWORD_RULES = {
    "Wants": ["zomato", "swiggy", "blinkit", "zepto", "uber", "ola", "rapido", "namma yatri", 
              "netflix", "spotify", "apple", "prime", "bookmyshow", "pvr", "inox", "cinema", 
              "starbucks", "kfc", "mcdonalds", "pizza", "burger", "dunzo", "amazon"],
    "Needs": ["rent", "electricity", "bescom", "act fiber", "jio", "airtel", "vi ", "water", "gas", 
              "milk", "grocery", "pharmacy", "medical", "hospital", "petrol", "shell", "hpcl", "bpcl"],
    "Financial": ["zerodha", "groww", "indmoney", "kite", "cdsl", "nsdl", "angel one", "upstox", 
                  "lic", "premium", "insurance", "loan", "emi", "credit card payment", "cred", "sip", "mutual fund"]
}

# ============================================================================
# PERSISTENCE ENGINE (Refactored for Supabase)
# ============================================================================

def save_all_data_callback():
    """Force immediate save of all data to Supabase."""
    if st.session_state.user is None:
        return
    
    user_id = st.session_state.user.id
    try:
        # Optimistic UI is handled by st.data_editor updating session_state
        # We sync the current state to DB
        db.sync_accounts(user_id, st.session_state.accounts)
        db.sync_fixed(user_id, st.session_state.fixed_costs)
        db.sync_obligations(user_id, st.session_state.obligations)
        db.sync_investments(user_id, st.session_state.investments)
        db.sync_illiquid_assets(user_id, st.session_state.illiquid_assets)
        db.sync_credit_cards(user_id, st.session_state.credit_cards)
        db.sync_capital_gains(user_id, st.session_state.capital_gains)
        db.sync_insurance_policies(user_id, st.session_state.insurance_policies)
        db.upsert_emergency_fund(user_id, st.session_state.emergency_fund)
        db.sync_goals(user_id, st.session_state.goals)
        st.toast("✅ Data synced to cloud", icon="☁️")
    except Exception as e:
        st.error(f"Error syncing data: {e}")

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="WealthOS",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    /* Hide Streamlit chrome noise only — never `header { display:none }` (breaks layout). */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(165deg, #0d1117 0%, #121820 50%, #0d1117 100%);
    }
    [data-testid="stHeader"] {
        background: rgba(13, 17, 23, 0.9);
        backdrop-filter: blur(6px);
        border-bottom: 1px solid #21262d;
    }
    .block-container {
        padding-top: 1.1rem;
        padding-bottom: 2rem;
    }
    [data-testid="stVerticalBlock"] > [style*="flex-direction: column"] > div {
        gap: 0.35rem;
    }
    .tier-badge {
        display: inline-block;
        border-radius: 999px;
        padding: 4px 12px;
        background: #238636;
        color: #ffffff;
        font-size: 0.85rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# AUTHENTICATION & STATE MANAGEMENT
# ============================================================================

if 'user' not in st.session_state:
    st.session_state.user = None
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

def handle_logout():
    st.session_state.user = None
    st.session_state.data_loaded = False
    st.rerun()

# --- AUTH UI ---
if st.session_state.user is None:
    st.title("💰 WealthOS")
    st.markdown(
        "**A personal CFO for salaried professionals in India.** Most money apps show you "
        "charts of what you already spent. This one tries the opposite: look at your income, "
        "debt and investments together, and say what to do next — which EMI to clear first, "
        "whether a SIP is actually costing you money while a credit card runs at 36%."
    )
    st.markdown(
        "**Getting started**  \n"
        "1. Sign up with any email and password.  \n"
        "2. Enter your approximate monthly take-home pay — that alone gets the dashboard working.  \n"
        "3. Add accounts, EMIs and investments as you go, or import a bank statement or Zerodha CSV.  \n"
        "4. Ask the AI tab questions about your own numbers."
    )
    st.info(
        "An early MVP, built solo — expect rough edges, and treat it as a prototype rather than "
        "financial advice. What you enter is visible only to your own account. Please don't upload "
        "real bank statements or account numbers; made-up figures work fine for trying it out."
    )
    st.caption("Code and product docs: github.com/TheTinyPenguinn/WealthOS")
    auth_tab1, auth_tab2 = st.tabs(["Login", "Sign Up"])
    
    with auth_tab1:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                try:
                    res = db.supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    msg = str(e)
                    if "403" in msg:
                        st.error(
                            "Login failed: 403 Forbidden. Check SUPABASE_URL/SUPABASE_ANON_KEY "
                            "and verify Email auth is enabled in Supabase."
                        )
                        st.caption(f"Auth error details: {msg}")
                    else:
                        st.error(f"Login failed: {e}")
    
    with auth_tab2:
        with st.form("signup_form"):
            new_email = st.text_input("Email")
            new_password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign Up", use_container_width=True):
                try:
                    res = db.signup_user(new_email, new_password)
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    st.error(f"Signup failed: {e}")
    st.stop()

# --- DATA LOADING (Strict Supabase) ---
user = st.session_state.user

if not st.session_state.data_loaded:
    with st.spinner("Loading your vault..."):
        data = db.load_all_data(user.id)
        if data:
            st.session_state.accounts = data["accounts"]
            st.session_state.fixed_costs = data["fixed_costs"]
            st.session_state.obligations = data["obligations"]
            st.session_state.investments = data["investments"]
            st.session_state.expenses = data["expenses"]
            st.session_state.illiquid_assets = data["illiquid_assets"]
            st.session_state.credit_cards = data["credit_cards"]
            st.session_state.user_profile = data["user_profile"] or {}
            st.session_state.capital_gains = data.get("capital_gains", pd.DataFrame())
            st.session_state.insurance_policies = data.get("insurance_policies", pd.DataFrame())
            st.session_state.emergency_fund = data.get(
                "emergency_fund", {"Target Months": 6, "Current Amount": 0.0, "Account Name": ""}
            )
            st.session_state.goals = data.get("goals", pd.DataFrame())
            
            settings = data["settings"]
            st.session_state.salary = settings.get("salary", 0.0)
            
            # --- API KEY FALLBACK LOGIC ---
            # 1. Check Supabase (User's personal key)
            # 2. Check st.secrets (Developer's shared key)
            db_api_key = settings.get("api_key", "")
            provider_for_key = _resolved_llm_provider()
            provider_env_key = {
                "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
            }.get(provider_for_key, "ANTHROPIC_API_KEY")
            secrets_api_key = _get_secret_or_env(provider_env_key)
            st.session_state.api_key = db_api_key if db_api_key else secrets_api_key
            
            _stored_model = settings.get("selected_model") or "gemini-3.8-flash"
            # Retired Gemini models fail every call; migrate a saved one forward.
            if _stored_model.startswith(("gemini-1.5", "gemini-2.0")):
                _stored_model = "gemini-3.8-flash"
            st.session_state.selected_model = _stored_model
            
            st.session_state.data_loaded = True
            st.rerun()

# ============================================================================
# DATA ENGINE - SUPABASE WRAPPERS
# ============================================================================

def save_expenses(df):
    """Wrapper for legacy calls, now uses Supabase clear-and-replace."""
    try:
        user_id = st.session_state.user.id
        db.supabase.table("expenses").delete().eq("user_id", user_id).execute()
        payload = []
        for _, row in df.iterrows():
            payload.append({
                "user_id": user_id,
                "date": pd.to_datetime(row["Date"]).isoformat(),
                "description": row["Description"],
                "amount": float(row["Amount"]),
                "category": row["Category"]
            })
        if payload:
            for i in range(0, len(payload), 500):
                db.supabase.table("expenses").insert(payload[i:i+500]).execute()
        return True
    except Exception as e:
        st.error(f"Error saving expenses: {e}")
        return False

def save_investments(df):
    """Wrapper for legacy calls, now uses Supabase snapshot sync."""
    try:
        db.sync_investments(st.session_state.user.id, df)
        return True
    except Exception as e:
        st.error(f"Error saving investments: {e}")
        return False

# ============================================================================
# PHASE 2 HELPERS
# ============================================================================

def profile_risk_details(profile: dict):
    age = int(profile.get("age", 0) or 0)
    target_retirement_age = int(profile.get("target_retirement_age", 60) or 60)
    ytr = target_retirement_age - age

    if ytr < 5:
        return "conservative", ytr, "80% debt / 20% equity"
    if ytr < 15:
        return "balanced", ytr, "50% debt / 50% equity"
    return "aggressive", ytr, "20% debt / 80% equity"


def _infer_tax_profile(annual_gross_income: float, user_id: str):
    """Estimate bracket and preferred regime from gross annual income + deductions."""
    gross_income = max(0.0, float(annual_gross_income or 0.0))
    deductions_payload = {"s80c_invested": 0.0, "s_nps_invested": 0.0, "s80d_total": 0.0}
    try:
        ded = get_deductions_summary(user_id, current_financial_year(), db.supabase)
        deductions_payload = {
            "s80c_invested": float(ded["s80c"]["invested"]),
            "s_nps_invested": float(ded["s_nps"]["invested"]),
            "s80d_total": float(ded["s80d"]["total"]),
        }
    except Exception:
        pass

    cmp = compare_regimes(gross_income=gross_income, deductions=deductions_payload)
    regime = cmp.get("recommended", "new")
    s80c = min(deductions_payload["s80c_invested"], 150000.0)
    s_nps = min(deductions_payload["s_nps_invested"], 50000.0)
    s80d = deductions_payload["s80d_total"]
    taxable_old = max(0.0, gross_income - 75000.0 - s80c - s_nps - s80d)
    taxable_new = max(0.0, gross_income - 75000.0)
    taxable = taxable_old if regime == "old" else taxable_new

    if regime == "old":
        if taxable <= 250000:
            bracket = 0
        elif taxable <= 500000:
            bracket = 5
        elif taxable <= 1000000:
            bracket = 20
        else:
            bracket = 30
    else:
        if taxable <= 300000:
            bracket = 0
        elif taxable <= 700000:
            bracket = 5
        elif taxable <= 1000000:
            bracket = 10
        elif taxable <= 1200000:
            bracket = 15
        elif taxable <= 1500000:
            bracket = 20
        else:
            bracket = 30
    return int(bracket), regime


def get_illiquid_net_value():
    illiquid_df = st.session_state.get("illiquid_assets", pd.DataFrame())
    if illiquid_df is None or illiquid_df.empty:
        return 0.0
    estimated = illiquid_df.get("Estimated Value", pd.Series(dtype=float)).apply(safe_float).sum()
    loan = illiquid_df.get("Loan Outstanding", pd.Series(dtype=float)).apply(safe_float).sum()
    return max(0.0, float(estimated - loan))


def get_credit_card_intelligence():
    cards_df = st.session_state.get("credit_cards", pd.DataFrame())
    if cards_df is None or cards_df.empty:
        return 0.0, 0.0, []

    total_limit = cards_df.get("Credit Limit", pd.Series(dtype=float)).apply(safe_float).sum()
    total_outstanding = cards_df.get("Current Outstanding", pd.Series(dtype=float)).apply(safe_float).sum()
    utilisation_pct = (total_outstanding / total_limit * 100) if total_limit > 0 else 0.0

    revolving_cost = 0.0
    apr_badges = []
    for _, row in cards_df.iterrows():
        outstanding = safe_float(row.get("Current Outstanding", 0.0))
        min_due = safe_float(row.get("Min Due Amount", 0.0))
        apr = safe_float(row.get("APR (%)", 0.0))
        revolve_base = max(0.0, outstanding - min_due)
        monthly_cost = revolve_base * apr / 1200
        revolving_cost += monthly_cost
        if apr > 20:
            card_name = row.get("Card Name", "Card")
            apr_badges.append(f"{card_name}: {apr:.1f}% APR — costs Rs {monthly_cost:,.0f}/mo. Kill first.")

    return float(utilisation_pct), float(revolving_cost), apr_badges

# ============================================================================
# UTILITIES
# ============================================================================

def safe_float(val, default=0.0):
    try:
        if val is None or pd.isna(val):
            return default
        # Handle string inputs with multiple decimals or invalid chars
        if isinstance(val, str):
            # Remove common currency symbols and commas
            clean_val = val.replace('₹', '').replace('$', '').replace(',', '').strip()
            # Check for multiple decimal points
            if clean_val.count('.') > 1:
                return default
            return float(clean_val)
        return float(val)
    except (ValueError, TypeError):
        return default

# ============================================================================
# INVESTMENT ENGINE - PRICE FETCHING WITH CACHING
# ============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_mf_nav(scheme_code):
    """Fetch current NAV for an Indian Mutual Fund via AMFI cache."""
    try:
        nav_data = get_nav(str(scheme_code).strip(), db.supabase)
        if not nav_data:
            return None
        nav = float(nav_data["nav"])
        return nav if nav > 0 else None
    except Exception:
        return None

@st.cache_data(ttl=600, show_spinner=False)  # Cache for 10 minutes
def fetch_live_price(ticker):
    """Fetch live price from yfinance with error handling."""
    if not YFINANCE_AVAILABLE or not ticker:
        return None
    
    # Clean ticker - remove any whitespace
    ticker = str(ticker).strip()
    if not ticker or ticker == 'nan':
        return None
        
    try:
        stock = yf.Ticker(ticker)
        
        # Method 1: Try history with multiple periods
        for period in ["5d", "1mo"]:
            try:
                data = stock.history(period=period)
                if data is not None and not data.empty and 'Close' in data.columns:
                    price = float(data['Close'].iloc[-1])
                    if price > 0:
                        return price
            except Exception:
                continue
        
        # Method 2: Try info dict
        try:
            info = stock.info
            if info:
                for key in ['regularMarketPrice', 'currentPrice', 'previousClose']:
                    price = info.get(key)
                    if price and float(price) > 0:
                        return float(price)
        except Exception:
            pass
                
    except Exception:
        pass
    
    return None

def get_portfolio_with_prices(investments_df):
    """Get portfolio dataframe with live prices and P/L calculations."""
    if investments_df.empty:
        return pd.DataFrame()
    
    import time
    
    portfolio = investments_df.copy()
    live_prices = []
    current_values = []
    unrealized_pls = []
    
    failed_tickers = []
    success_count = 0
    
    for idx, row in portfolio.iterrows():
        ticker = row.get('Ticker', '')
        asset_type = row.get('Type', 'Stock')
        qty = float(row.get('Quantity', 0))
        avg_price = float(row.get('Avg_Buy_Price', 0))
        
        live_price = None
        
        if asset_type == 'Mutual Fund':
            # Fetch NAV via mfapi.in using ISIN (e.g. INF123456789)
            live_price = fetch_mf_nav(ticker)
        else:
            live_price = fetch_live_price(ticker)
            # Small delay to avoid rate limiting (only if not cached)
            if idx > 0:
                time.sleep(0.1)

        if live_price is None:
            failed_tickers.append(ticker)
            live_price = avg_price  # Fallback to avg price
        else:
            success_count += 1
        
        current_value = qty * live_price
        cost_basis = qty * avg_price
        unrealized_pl = current_value - cost_basis
        
        live_prices.append(live_price)
        current_values.append(current_value)
        unrealized_pls.append(unrealized_pl)
    
    portfolio['Live_Price'] = live_prices
    portfolio['Current_Value'] = current_values
    portfolio['Unrealized_PL'] = unrealized_pls
    
    if failed_tickers:
        st.toast(f"⚠️ Price fetch failed for: {', '.join(failed_tickers[:3])}{'...' if len(failed_tickers) > 3 else ''}")
    elif success_count > 0:
        st.toast(f"✅ Fetched live prices for {success_count} assets")
    
    return portfolio


# ============================================================================
# SMART CSV PARSER FOR INDIAN BANK STATEMENTS
# ============================================================================


def parse_bank_csv(uploaded_file):
    """Parse bank / WealthOS transaction CSV (see app.utils.bank_statement_csv)."""
    try:
        raw = uploaded_file.getvalue()
        df, err = parse_bank_statement_csv_from_bytes(raw)
        if err:
            st.error(err)
            return None
        return df
    except Exception as e:
        st.error(f"Error parsing CSV: {e}")
        return None

def deduplicate_transactions(new_df, existing_df):
    """
    Smart Fuzzy Merge: 
    1. If abs(New_Amount - Existing_Amount) < 0.01 AND Date is within ±2 days.
    2. DISCARD the new bank row to preserve user's manual categorization.
    3. Logs skipped transactions to terminal for safety.
    """
    if existing_df.empty:
        return new_df
    
    # Create copies
    new = new_df.copy()
    existing = existing_df.copy()
    
    # Ensure Date format
    new['Date'] = pd.to_datetime(new['Date'])
    existing['Date'] = pd.to_datetime(existing['Date'])
    
    to_add = []
    skipped_count = 0
    
    for _, new_row in new.iterrows():
        n_amt = float(new_row['Amount'])
        n_date = new_row['Date']
        
        # Check for duplicate
        is_duplicate = False
        for _, exist_row in existing.iterrows():
            e_amt = float(exist_row['Amount'])
            e_date = exist_row['Date']
            
            amt_match = abs(n_amt - e_amt) < 0.01
            date_match = abs((n_date - e_date).days) <= 2
            
            if amt_match and date_match:
                is_duplicate = True
                print(f"⚠️ Skipped Duplicate: {n_date.date()} | ₹{n_amt} (Matches existing entry)")
                break
        
        if not is_duplicate:
            to_add.append(new_row)
        else:
            skipped_count += 1
            
    if skipped_count > 0:
        print(f"Total duplicates removed: {skipped_count}")
        
    return pd.DataFrame(to_add)

# ============================================================================
# ZERODHA IMPORT LOGIC
# ============================================================================

def find_header_row_zerodha(df, max_rows=30):
    """
    Find the header row in Zerodha files by looking for specific keywords.
    Zerodha files often have ~20 rows of metadata before the actual header.
    """
    header_keywords = ["symbol", "instrument", "isin", "qty", "quantity", "avg"]
    
    for idx in range(min(max_rows, len(df))):
        row_values = [str(v).lower().strip() for v in df.iloc[idx].values if pd.notna(v)]
        matches = sum(1 for kw in header_keywords if any(kw in val for val in row_values))
        if matches >= 2:  # At least 2 keyword matches = likely header
            return idx
    return None

def read_sheet_with_header_detection(xls, sheet_name):
    """Read an Excel sheet and detect the actual header row."""
    # First read without header to scan for header row
    df_raw = pd.read_excel(xls, sheet_name, header=None)
    header_idx = find_header_row_zerodha(df_raw)
    
    if header_idx is not None:
        # Re-read with correct header
        df = pd.read_excel(xls, sheet_name, header=header_idx)
    else:
        # Fallback: assume first row is header
        df = pd.read_excel(xls, sheet_name)
    
    return df

def parse_zerodha_file(uploaded_file):
    """
    Parses Zerodha XLSX or CSV with smart header detection.
    Handles ~20 rows of metadata/junk before actual data.
    Ignores 'Combined'/'Holdings' sheets to prevent duplicates.
    """
    try:
        df = pd.DataFrame()
        
        # 1. Handle Excel (Multi-sheet)
        if uploaded_file.name.endswith('.xlsx'):
            if not OPENPYXL_AVAILABLE:
                st.error("Please install openpyxl: pip install openpyxl")
                return None
                
            xls = pd.ExcelFile(uploaded_file)
            sheet_names = xls.sheet_names
            
            # Sheets to ignore (contain duplicates)
            ignore_sheets = ['Combined', 'Holdings', 'Summary']
            
            # Prioritize specific sheets
            frames = []
            priority_sheets = ['Equity', 'Mutual Funds']
            
            for sheet in priority_sheets:
                if sheet in sheet_names:
                    sheet_df = read_sheet_with_header_detection(xls, sheet)
                    if not sheet_df.empty:
                        frames.append(sheet_df)
            
            # If no priority sheets found, try other sheets (excluding ignored ones)
            if not frames:
                for sheet in sheet_names:
                    if sheet not in ignore_sheets:
                        sheet_df = read_sheet_with_header_detection(xls, sheet)
                        if not sheet_df.empty:
                            frames.append(sheet_df)
                            break  # Just take the first valid sheet
                
            if frames:
                df = pd.concat(frames, ignore_index=True)
            else:
                st.error("No valid data sheets found in Excel file")
                return None
                
        # 2. Handle CSV with header detection
        else:
            # First read without header to scan
            uploaded_file.seek(0)
            df_raw = pd.read_csv(uploaded_file, header=None)
            header_idx = find_header_row_zerodha(df_raw)
            
            # Re-read with correct header
            uploaded_file.seek(0)
            if header_idx is not None:
                df = pd.read_csv(uploaded_file, header=header_idx)
            else:
                df = pd.read_csv(uploaded_file)

        # 3. Rename Columns (Normalize to our standard)
        # Map all common Zerodha column name variations
        col_map = {
            'Instrument': 'Ticker', 'Symbol': 'Ticker', 'Stock Symbol': 'Ticker',
            'Qty.': 'Quantity', 'Quantity': 'Quantity', 'Quantity Available': 'Quantity',
            'Avg. cost': 'Avg_Buy_Price', 'Buy Average': 'Avg_Buy_Price', 'Average Price': 'Avg_Buy_Price'
        }
        df = df.rename(columns=col_map)
        
        # Check required columns
        required = ['Ticker', 'Quantity', 'Avg_Buy_Price']
        if not all(col in df.columns for col in required):
            st.error(f"Missing columns. Found: {df.columns.tolist()}")
            return None
        
        # Drop rows where Ticker is NaN or empty
        df = df.dropna(subset=['Ticker'])
        df = df[df['Ticker'].astype(str).str.strip() != '']

        # 4. Smart Type Detection & Cleanup
        def process_row(row):
            ticker = str(row['Ticker']).strip().upper()
            
            # Detect Type
            asset_type = "Stock"
            if "BEES" in ticker or "ETF" in ticker: 
                asset_type = "ETF"
            elif "SGB" in ticker: 
                asset_type = "Gold"
            elif "INF" in ticker: 
                asset_type = "Mutual Fund"  # ISIN for MF usually starts with INF
            
            # Add .NS suffix (only for Stocks/ETFs/Gold, not Mutual Funds)
            if asset_type in ["Stock", "ETF", "Gold"] and not ticker.endswith('.NS'):
                ticker = f"{ticker}.NS"
                
            return pd.Series([ticker, asset_type])

        df[['Ticker', 'Type']] = df.apply(process_row, axis=1)
        
        # Ensure numeric columns
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0)
        df['Avg_Buy_Price'] = pd.to_numeric(df['Avg_Buy_Price'], errors='coerce').fillna(0)
        
        # Return cleaned data
        return df[['Ticker', 'Type', 'Quantity', 'Avg_Buy_Price']]
        
    except Exception as e:
        st.error(f"Error parsing file: {e}")
        return None

# ============================================================================
# USER-TRAINABLE RULES ENGINE
# ============================================================================

def load_user_rules():
    """Load user-defined rules from rules.json."""
    try:
        if os.path.exists("rules.json"):
            with open("rules.json", "r") as f:
                rules = json.load(f)
                # Safety check: ensure rules is a dictionary
                if isinstance(rules, dict):
                    return rules
                else:
                    st.warning("⚠️ rules.json corrupted. Using default rules.")
                    return {}
    except Exception:
        pass
    return {}

def save_user_rule(keyword, category):
    """Save a user-defined rule to rules.json."""
    try:
        rules = load_user_rules()
        rules[keyword.lower()] = category
        with open("rules.json", "w") as f:
            json.dump(rules, f, indent=2)
        return True
    except Exception:
        return False

# ============================================================================
# AUTO-CATEGORIZATION ENGINE (with UPI logic)
# ============================================================================

def auto_categorize(df, force_overwrite=False):
    """Auto-categorize transactions with User-Trainable rules."""
    changes = 0
    df = df.copy()
    user_rules = load_user_rules()
    
    for idx, row in df.iterrows():
        current_cat = str(row.get('Category', 'Needs')).strip()
        desc = str(row.get('Description', ''))
        desc_lower = desc.lower()
        amount = float(row.get('Amount', 0))
        
        # Safety Lock: Skip manually tagged categories
        protected_categories = ['One-Time', 'Financial', 'Asset', 'Income']
        if current_cat in protected_categories:
            continue
        
        # Only apply rules to Needs, Wants, or empty categories
        if current_cat not in ['Needs', 'Wants', ''] and not force_overwrite:
            continue
        
        new_cat = None
        new_desc = desc
        
        # Rule 1: Income detection (positive amount)
        if amount > 0:
            new_cat = 'Income'
        else:
            # Rule 2: UPI Logic - mark for verification
            if 'upi' in desc_lower:
                new_cat = 'Needs'
                if '(Verify)' not in desc:
                    new_desc = desc + ' (Verify)'
            else:
                # Rule 3: User Rules (Priority)
                matched = False
                for keyword, category in user_rules.items():
                    if keyword in desc_lower:
                        new_cat = category
                        matched = True
                        break
                
                # Rule 4: Hardcoded Rules (Fallback)
                if not matched:
                    for category, keywords in KEYWORD_RULES.items():
                        if any(kw in desc_lower for kw in keywords):
                            new_cat = category
                            break
        
        if new_cat and (new_cat != current_cat or new_desc != desc):
            df.at[idx, 'Category'] = new_cat
            df.at[idx, 'Description'] = new_desc
            changes += 1
    
    return df, changes

# ============================================================================
# AI CONTEXT ENGINE
# ============================================================================

def generate_financial_context(net_worth, liquid_net_worth, total_debt, true_burn, surplus, fixed_living, total_emi, csv_variable_spend, avg_interest):
    """Generates a summary string of the user's financial health for the AI using passed arguments."""
    try:
        salary = st.session_state.get('salary', 0.0)
        
        summary = f"""
        💰 CASH FLOW POWER (MONTHLY):
        - Income: ₹{salary:,.2f}
        - Effective Burn: ₹{true_burn:,.2f} (Fixed: ₹{fixed_living:,.2f} + EMI: ₹{total_emi:,.2f} + Variable: ₹{csv_variable_spend:,.2f})
        - 🚀 INVESTIBLE SURPLUS: ₹{surplus:,.2f} / month ({(surplus/salary*100) if salary > 0 else 0:.1f}%)

        🏦 BALANCE SHEET & DEBT:
        - Liquid Net Worth: ₹{liquid_net_worth:,.2f}
        - Total Debt Balance: ₹{total_debt:,.2f}
        - True Net Worth: ₹{net_worth:,.2f}
        - Avg Debt Interest Rate: {avg_interest:.1f}%

        🔮 STRATEGY CHECK:
        - If Surplus > 0 and Interest Rate > 8%: Consider debt prepayment.
        - If Surplus > 0 and Interest Rate < 8%: Consider investing surplus.
        - Focus on reducing high-interest debt first.
        """
        return summary
    except Exception as e:
        return f"Error generating context: {e}"

def analyze_survival_metrics(df, salary):
    """Calculates survival stats: UPI Bleed, Hourly Wage, Zero Days."""
    try:
        # 1. UPI Bleed (Death by Micro-cuts)
        upi_bleed = 0.0
        if not df.empty:
            # Filter: Description contains 'UPI' AND Amount is expense AND Amount < 500
            mask = (df['Description'].str.contains('UPI', case=False, na=False)) & (df['Amount'] < 0) & (df['Amount'].abs() < 500)
            upi_bleed = df[mask]['Amount'].abs().sum()

        # 2. Real Hourly Wage (Salary - Needs) / 160 hours
        monthly_needs = 0.0
        if not df.empty and 'Category' in df.columns:
            # Estimate needs from current data (simple sum of 'Needs' category)
            # For a more robust stat, we might average it, but simple sum is fine for MVP
            monthly_needs = df[df['Category'] == 'Needs']['Amount'].abs().sum()
        
        # Protect against negative wage
        real_hourly = max(0, (salary - monthly_needs) / 160)

        # 3. Zero Days (Days with ₹0 spend)
        zero_days = 0
        if not df.empty:
            today = pd.Timestamp.now()
            start_date = today - pd.Timedelta(days=30)
            # Filter for last 30 days
            recent_df = df[(df['Date'] >= start_date) & (df['Date'] <= today)]
            # Count unique days with expenses
            spend_days = recent_df[recent_df['Amount'] < 0]['Date'].dt.date.nunique()
            zero_days = 30 - spend_days

        return upi_bleed, real_hourly, zero_days
    except Exception:
        return 0.0, 0.0, 0

def analyze_subscriptions(df):
    """Analyze recurring subscriptions/expenses with smart filtering."""
    try:
        if df.empty:
            return pd.DataFrame()
        
        # Filter for expenses only, exclude certain categories
        exclude_categories = ['One-Time', 'Income', 'Asset', 'Financial']
        expenses = df[(df['Amount'] < 0) & (~df['Category'].isin(exclude_categories))].copy()
        expenses['Amount'] = expenses['Amount'].abs()
        expenses['Desc_Prefix'] = expenses['Description'].str[:10].str.lower()
        expenses['DayOfMonth'] = expenses['Date'].dt.day
        
        # Group by description prefix
        grouped = expenses.groupby('Desc_Prefix').agg({
            'Amount': ['count', 'sum', 'mean', 'min', 'max'],
            'Date': ['min', 'max'],
            'DayOfMonth': ['nunique', 'std']
        }).round(2)
        
        # Flatten column names
        grouped.columns = ['Count', 'Monthly_Avg', 'Mean', 'Min_Amount', 'Max_Amount', 
                        'First_Date', 'Last_Date', 'Unique_Days', 'Day_Std']
        
        # Check if recurring (3+ transactions across 3+ months, consistent dates)
        def is_recurring(group):
            if group['Count'] < 3:
                return False
            # Check if spans at least 3 unique months
            months = pd.to_datetime(group[['First_Date', 'Last_Date']].values.flatten()).dt.to_period('M')
            return months.nunique() >= 3 and pd.notna(group['Day_Std']) and group['Day_Std'] <= 5
        
        grouped['Is_Recurring'] = grouped.apply(is_recurring, axis=1)
        
        # Calculate metrics
        grouped['Yearly_Cost'] = grouped['Monthly_Avg'] * 12
        grouped['Inflation'] = grouped['Max_Amount'] - grouped['Min_Amount']
        grouped['Status'] = grouped['Inflation'].apply(lambda x: "⚠️ Price Hike" if x > 50 else "Stable")
        
        # Return sorted by yearly cost
        return grouped[grouped['Is_Recurring'] & (grouped['Yearly_Cost'] > 0)].sort_values('Yearly_Cost', ascending=False)
        
    except Exception:
        return pd.DataFrame()

def plot_runway_impact(liquid_net_worth, monthly_burn, upi_bleed):
    """Create runway impact visualization with gain calculation."""
    try:
        if monthly_burn <= 0:
            return None
            
        current_runway = liquid_net_worth / monthly_burn
        potential_runway = liquid_net_worth / max(1, (monthly_burn - upi_bleed))
        gain = potential_runway - current_runway
        
        if not PLOTLY_AVAILABLE:
            return None
            
        fig = go.Figure()
        
        # Add bars
        fig.add_trace(go.Bar(
            y=['Current Path', 'Stop Micro-Spends'],
            x=[current_runway, potential_runway],
            orientation='h',
            marker_color=['#EF553B', '#00CC96'],
            text=[f'{current_runway:.1f} months', f'{potential_runway:.1f} months'],
            textposition='auto'
        ))
        
        fig.update_layout(
            title=f"⚡ Stop Micro-Spends to gain +{gain:.1f} Months of Freedom",
            xaxis_title='Months',
            yaxis_title='',
            height=250,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='white'),
            showlegend=False
        )
        
        return fig
        
    except Exception:
        return None

# ============================================================================
# METRICS CALCULATION
# ============================================================================

def calculate_true_burn(expenses_df, fixed_df, obligations_df, salary):
    """Calculate true burn rate using hybrid logic."""
    # Calculate Monthly Floor from Fixed Costs
    monthly_floor = 0.0
    if not fixed_df.empty:
        for _, row in fixed_df.iterrows():
            if row['Frequency'] == 'Monthly':
                monthly_floor += row['Amount']
            elif row['Frequency'] == 'Yearly':
                monthly_floor += row['Amount'] / 12
    
    # Calculate Monthly Obligations
    monthly_obligations = 0.0
    if not obligations_df.empty:
        monthly_obligations = obligations_df['Amount'].sum()
    
    # Calculate Variable Spend from CSV
    csv_wants = 0.0
    csv_needs = 0.0
    if not expenses_df.empty:
        # Filter for last 30 days for variable spend
        today = pd.Timestamp.now()
        start_date = today - pd.Timedelta(days=30)
        recent_df = expenses_df[(pd.to_datetime(expenses_df['Date']) >= start_date) & 
                              (pd.to_datetime(expenses_df['Date']) <= today)]
        
        if not recent_df.empty:
            csv_wants = abs(recent_df[recent_df['Category'] == 'Wants']['Amount'].sum())
            csv_needs = abs(recent_df[recent_df['Category'] == 'Needs']['Amount'].sum())
    
    # Effective Needs = Higher of (CSV Needs vs Monthly Floor)
    effective_needs = max(csv_needs, monthly_floor)
    
    # Total Monthly Burn = Effective Needs + CSV Wants + Monthly Obligations
    total_monthly_burn = effective_needs + csv_wants + monthly_obligations
    
    # Real Hourly Wage
    real_hourly_wage = (salary - total_monthly_burn) / 160
    
    return total_monthly_burn, monthly_floor, monthly_obligations, effective_needs, csv_wants, real_hourly_wage

def calculate_metrics(expenses_df, investments_df, accounts_df):
    """Calculate dashboard metrics with Cash Flow First logic."""
    # Get inputs
    salary = safe_float(st.session_state.get('salary', 0.0))
    fx_rate = get_usd_rate()
    
    # 1. FIXED COSTS (Monthly Floor)
    monthly_floor = 0.0
    if 'fixed_costs' in st.session_state:
        for _, row in st.session_state.fixed_costs.iterrows():
            amt = safe_float(row.get('Amount', 0.0))
            freq = row.get('Frequency', 'Monthly')
            if freq == 'Monthly': monthly_floor += amt
            elif freq == 'Quarterly': monthly_floor += amt / 3
            elif freq == 'Half-Yearly': monthly_floor += amt / 6
            elif freq == 'Yearly': monthly_floor += amt / 12
            
    # 2. DEBT & OBLIGATIONS
    total_emi = 0.0
    monthly_interest_burn = 0.0
    total_debt_balance = 0.0
    weighted_rate_sum = 0.0
    
    if 'obligations' in st.session_state:
        for _, row in st.session_state.obligations.iterrows():
            if row.get('Type') == 'Loan':
                total_emi += safe_float(row.get('Amount', 0.0))
                principal = safe_float(row.get('Current Balance', 0.0))
                if row.get('Currency') == 'USD': principal *= fx_rate
                
                total_debt_balance += principal
                rate = safe_float(row.get('Interest Rate (%)', 0.0))
                monthly_interest_burn += (principal * (rate / 100)) / 12
                weighted_rate_sum += principal * rate

    # Calculate Weighted Avg Interest
    avg_interest = (weighted_rate_sum / total_debt_balance) if total_debt_balance > 0 else 0.0

    # 3. VARIABLE SPEND (From CSV)
    csv_variable_spend = 0.0
    csv_needs = 0.0
    if not expenses_df.empty:
        today = pd.Timestamp.now()
        recent = expenses_df[(pd.to_datetime(expenses_df['Date']) >= today - pd.Timedelta(days=30)) & (pd.to_datetime(expenses_df['Date']) <= today)]
        if not recent.empty:
            # Exclude large one-off wants > 20k from "Burn Rate" (treat as anomalies)
            wants = recent[recent['Category'] == 'Wants']
            needs = recent[recent['Category'] == 'Needs']
            csv_variable_spend = abs(wants[wants['Amount'].abs() <= 20000]['Amount'].sum())
            csv_needs = abs(needs['Amount'].sum())

    # 4. BURN & SURPLUS (Fixed: Add unexpected_needs)
    unexpected_needs = max(0, csv_needs - monthly_floor)
    true_burn = monthly_floor + total_emi + csv_variable_spend + unexpected_needs
    surplus = max(0, salary - true_burn)
    surplus_margin = (surplus / salary * 100) if salary > 0 else 0

    # 5. NET WORTH ACCOUNTS (Fixed: No Double Counting)
    bank_cash = 0.0
    credit_card = 0.0
    investments_sidebar = 0.0
    rsu_real_value = 0.0
    
    for _, row in accounts_df.iterrows():
        val = safe_float(row.get('Balance', 0.0))
        if row.get('Currency') == 'USD': val *= fx_rate
        
        t = row.get('Type', 'Bank/Cash')
        account_name = str(row.get('Account Name', '')).lower()
        
        # Strict Loan Segregation: Skip any loan/debt entries
        if t == 'Loan' or 'loan' in account_name or 'debt' in account_name:
            st.warning(f"⚠️ '{row.get('Account Name', 'Unknown')}' ignored. Please move loans to 'Financial Obligations'.")
            continue
        
        if t == 'Bank/Cash': bank_cash += val
        elif t == 'Credit Card': credit_card += abs(val)  # always treat as positive liability
        elif 'Investment' in t: 
            investments_sidebar += val
            # RSU Logic: Check if account name contains RSU (case-insensitive)
            if 'rsu' in account_name:
                rsu_real_value += val

    # 6. PORTFOLIO (Zerodha)
    csv_portfolio_value = 0.0
    if not investments_df.empty:
        portfolio = get_portfolio_with_prices(investments_df)
        if not portfolio.empty and 'Current_Value' in portfolio.columns:
            csv_portfolio_value = portfolio['Current_Value'].sum()

    # 7. Illiquid assets (net of associated loans)
    illiquid_net = get_illiquid_net_value()

    # Final Totals
    total_portfolio = csv_portfolio_value + investments_sidebar
    net_liquidity = bank_cash - credit_card 
    # Include credit card outstanding in dedicated module to debt accounting.
    cards_df = st.session_state.get("credit_cards", pd.DataFrame())
    credit_card_outstanding = 0.0
    if cards_df is not None and not cards_df.empty:
        credit_card_outstanding = cards_df.get("Current Outstanding", pd.Series(dtype=float)).apply(safe_float).sum()

    total_debt_balance += credit_card_outstanding
    total_debt_all = total_debt_balance
    net_worth = (net_liquidity + total_portfolio + illiquid_net) - total_debt_balance
    liquid_net_worth = net_worth - illiquid_net

    return net_worth, liquid_net_worth, total_debt_all, total_portfolio, true_burn, surplus_margin, surplus, monthly_interest_burn, avg_interest, rsu_real_value, monthly_floor, total_emi, csv_variable_spend, unexpected_needs, illiquid_net


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if 'parsed_csv' not in st.session_state:
    st.session_state.parsed_csv = pd.DataFrame(columns=['Date', 'Description', 'Amount', 'Category'])
if 'ocr_transactions' not in st.session_state:
    st.session_state.ocr_transactions = []
if 'tax_investments' not in st.session_state:
    st.session_state.tax_investments = pd.DataFrame(columns=["Instrument Type", "Amount Invested", "Notes"])
if 'tax_fy_loaded' not in st.session_state:
    st.session_state.tax_fy_loaded = ""
if 'capital_gains' not in st.session_state:
    st.session_state.capital_gains = pd.DataFrame(
        columns=["Asset Name", "Asset Type", "Buy Date", "Buy Price", "Sell Date", "Sell Price", "Units", "Notes"]
    )
if 'insurance_policies' not in st.session_state:
    st.session_state.insurance_policies = pd.DataFrame(
        columns=["Policy Name", "Policy Type", "Insurer", "Annual Premium", "Sum Assured", "Maturity Value", "Start Date", "Maturity Date", "Is Active", "Notes"]
    )
if 'emergency_fund' not in st.session_state:
    st.session_state.emergency_fund = {"Target Months": 6, "Current Amount": 0.0, "Account Name": ""}
if 'goals' not in st.session_state:
    st.session_state.goals = pd.DataFrame(
        columns=[
            "Name",
            "Goal Type",
            "Target Amount",
            "Target Date",
            "Current Amount",
            "Priority",
            "Ring Fenced",
            "Recommended Instrument",
            "Notes",
        ]
    )

if 'illiquid_assets' not in st.session_state:
    st.session_state.illiquid_assets = pd.DataFrame(
        columns=["Asset Type", "Name", "Estimated Value", "Loan Outstanding", "Notes"]
    )
if 'credit_cards' not in st.session_state:
    st.session_state.credit_cards = pd.DataFrame(
        columns=["Card Name", "Credit Limit", "Current Outstanding", "Billing Date", "Payment Due Date", "APR (%)", "Min Due Amount"]
    )
if 'user_profile' not in st.session_state:
    st.session_state.user_profile = {}

# --- PROFILE SETUP PAGE (first-time users, and reopened from the sidebar) ---
if 'show_profile' not in st.session_state:
    st.session_state.show_profile = False

_first_time_setup = not st.session_state.user_profile or st.session_state.user_profile.get("age") is None

if _first_time_setup or st.session_state.show_profile:
    _saved = st.session_state.user_profile or {}
    if _first_time_setup:
        st.title("👤 Profile Setup")
        st.caption("Set up your profile to unlock retirement-based risk guidance and auto tax slab estimation.")
    else:
        st.title("👤 Your Profile")
        st.caption("Update your details. Saving recalculates everything that depends on them.")
        if st.button("← Back to dashboard"):
            st.session_state.show_profile = False
            st.rerun()
    with st.form("profile_setup_form"):
        age = st.number_input("Age", min_value=18, max_value=100, value=int(_saved.get("age") or 28))
        target_retirement_age = st.number_input(
            "Target Retirement Age",
            min_value=40,
            max_value=80,
            value=int(_saved.get("target_retirement_age") or 60),
        )
        pay_period = st.selectbox("Fixed Pay Period", options=["Monthly", "Yearly"], index=0)
        pay_basis = st.selectbox(
            "Pay Entry Type",
            options=["Before deductions (Gross)", "After deductions (Net In-hand)"],
            index=0,
        )
        fixed_pay = st.number_input(
            f"Fixed Pay ({'₹ / month' if pay_period == 'Monthly' else '₹ / year'})",
            min_value=0.0,
            value=float(st.session_state.get("salary", 0.0)) if pay_period == "Monthly" else float(st.session_state.get("salary", 0.0)) * 12.0,
        )
        annual_deductions = st.number_input(
            "Estimated yearly deductions (PF/NPS/tax/etc) used for tax slab calc",
            min_value=0.0,
            value=0.0,
        )
        _income_types = ["salaried", "freelance", "business"]
        _saved_income_type = _saved.get("income_type") or "salaried"
        income_type = st.selectbox(
            "Income Type",
            options=_income_types,
            index=_income_types.index(_saved_income_type) if _saved_income_type in _income_types else 0,
        )

        annual_input = float(fixed_pay) if pay_period == "Yearly" else float(fixed_pay) * 12.0
        if pay_basis == "Before deductions (Gross)":
            annual_gross_for_tax = annual_input
            annual_take_home = max(0.0, annual_input - float(annual_deductions))
        else:
            annual_take_home = annual_input
            annual_gross_for_tax = annual_input + float(annual_deductions)
        monthly_income = annual_take_home / 12.0 if annual_take_home > 0 else 0.0

        estimated_tax_bracket, estimated_regime = _infer_tax_profile(annual_gross_for_tax, st.session_state.user.id)
        st.info(
            f"Estimated tax slab from entered income and deductions: "
            f"{estimated_tax_bracket}% ({estimated_regime.upper()} regime)."
        )
        st.caption(
            f"Planning monthly income set to ₹{monthly_income:,.0f}; "
            f"tax slab estimation uses gross annual income ₹{annual_gross_for_tax:,.0f}."
        )
        if st.form_submit_button("Save Profile" if _first_time_setup else "Save Changes", use_container_width=True):
            profile_payload = {
                "age": age,
                "target_retirement_age": target_retirement_age,
                "monthly_income": monthly_income,
                "income_type": income_type,
                "tax_bracket": estimated_tax_bracket,
                "tax_regime": estimated_regime,
            }
            saved = db.upsert_user_profile(st.session_state.user.id, profile_payload)
            st.session_state.user_profile = profile_payload
            # The dashboard reads user_settings.salary, not user_profile.monthly_income,
            # so setup has to write both or the dashboard stays empty until the user
            # retypes their pay in the sidebar.
            st.session_state.salary = monthly_income
            db.sync_settings(
                st.session_state.user.id,
                monthly_income,
                st.session_state.api_key,
                st.session_state.selected_model,
            )
            if saved:
                st.success("Profile saved.")
            else:
                st.warning("Profile stored for this session. Run DB migrations to persist user_profile.")
            st.session_state.show_profile = False
            st.rerun()
    st.stop()

# --- SIDEBAR - RICH CLASSIC DESIGN ---
st.sidebar.title("💰 WealthOS")

if st.sidebar.button("👤 Profile", use_container_width=True):
    st.session_state.show_profile = True
    st.rerun()

# 1. 📣 Feedback Hub (Prioritized at Top)
with st.sidebar.expander("📣 Report Bug / Suggest Idea", expanded=False):
    with st.form(key="feedback_form", clear_on_submit=True):
        f_type = st.selectbox("Type", ["🪲 Bug", "💡 Idea", "⚖️ Math Error", "🎨 UI"])
        f_priority = st.radio("Priority", ["Low", "Med", "High"], horizontal=True)
        f_details = st.text_area("Details", help="Please describe the issue or suggestion.")
        if st.form_submit_button("Submit Feedback", use_container_width=True):
            if f_details:
                net_worth, liquid_net_worth, total_debt, total_portfolio, true_burn, surplus_margin, surplus, monthly_interest_burn, avg_interest, rsu_real_value, monthly_floor, total_emi, csv_variable_spend, unexpected_needs, illiquid_net = calculate_metrics(
                    st.session_state.expenses,
                    st.session_state.investments,
                    st.session_state.accounts
                )
                metadata = {
                    "model": st.session_state.get('selected_model'),
                    "net_worth": net_worth,
                    "liquid_net_worth": liquid_net_worth,
                    "total_debt": total_debt
                }
                if db.insert_feedback(st.session_state.user.id, f_type, f_details, metadata):
                    st.success("Thanks for the feedback!")
                else:
                    st.error("Failed to send feedback.")

# 2. Metric Summary
total_portfolio = 0.0
if not st.session_state.investments.empty:
    _sidebar_portfolio = get_portfolio_with_prices(st.session_state.investments)
    if not _sidebar_portfolio.empty and 'Current_Value' in _sidebar_portfolio.columns:
        total_portfolio = _sidebar_portfolio['Current_Value'].sum()
    else:
        total_portfolio = (st.session_state.investments['Quantity'] * st.session_state.investments['Avg_Buy_Price']).sum()

liquid_cash = 0.0
total_debt_balance = 0.0
if not st.session_state.accounts.empty:
    # Only Bank/Cash accounts count as liquid (exclude Investment and Credit Card accounts)
    liquid_cash = st.session_state.accounts[st.session_state.accounts['Type'] == 'Bank/Cash']['Balance'].sum()
    total_debt_balance = st.session_state.accounts[st.session_state.accounts['Type'] == 'Credit Card']['Balance'].abs().sum()

m1, m2, m3 = st.sidebar.columns(3)
with m1:
    st.caption("Net Liquidity")
    st.markdown(f"**₹{liquid_cash:,.0f}**")
with m2:
    st.caption("Total Debt")
    st.markdown(f"**₹{total_debt_balance:,.0f}**")
with m3:
    st.caption("Investments")
    st.markdown(f"**₹{total_portfolio:,.0f}**")

st.sidebar.divider()

# 2. ⚙️ Configuration
with st.sidebar.expander("⚙️ Configuration", expanded=True):
    salary_input = st.number_input("Monthly Salary (₹)", value=float(st.session_state.get('salary', 0.0)), step=5000.0, format="%.2f")
    if salary_input != st.session_state.get('salary', 0.0):
        st.session_state.salary = salary_input
        db.sync_settings(st.session_state.user.id, salary_input, st.session_state.api_key, st.session_state.selected_model)
        st.toast("✅ Salary updated", icon="💰")

    current_provider = _resolved_llm_provider()
    provider_label = {
        "gemini": "Gemini API Key",
        "openai": "OpenAI API Key",
        "anthropic": "Anthropic API Key",
    }.get(current_provider, "LLM API Key")
    provider_env_key = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(current_provider, "ANTHROPIC_API_KEY")
    api_key_placeholder = (
        "Using shared key"
        if _get_secret_or_env(provider_env_key) and not st.session_state.get('api_key')
        else "Enter your personal key"
    )
    api_key_input = st.text_input(
        provider_label,
        type="password",
        value=st.session_state.get('api_key', ''),
        placeholder=api_key_placeholder,
        help="Leave blank to use the shared key, or enter your own.",
    )
    if api_key_input != st.session_state.get('api_key', ''):
        st.session_state.api_key = api_key_input
        db.sync_settings(st.session_state.user.id, st.session_state.salary, api_key_input, st.session_state.selected_model)
        st.toast("✅ API Key updated", icon="🔑")

# 3. 🏠 Core Data
# --- ACCOUNTS & CASH ---
with st.sidebar.expander("🏦 Accounts & Cash", expanded=False):
    st.caption("Bank accounts, credit cards, and manual investments (RSU, PPF, Gold).")
    st.info("📌 **Important**: Loans should now be entered in the 'Financial Obligations' section below to avoid double counting.")
    
    # Schema Upgrade: Add Currency column if missing
    if 'Currency' not in st.session_state.accounts.columns:
        st.session_state.accounts['Currency'] = 'INR'
    
    # Safe Data Migration: Convert old schema to new
    if 'schema_migrated_v2' not in st.session_state:
        st.session_state.accounts['Type'] = st.session_state.accounts['Type'].replace({
            'Asset': 'Bank/Cash',
            'Liability': 'Loan',
            'Investment': 'Investment (Non-Zerodha)'
        })
        st.session_state.schema_migrated_v2 = True
        st.warning("⚠️ Schema Updated: Please manually categorize your RSUs as 'Investment (Non-Zerodha)' and Credit Cards as 'Credit Card'.")
    
    edited_accounts = st.data_editor(
        st.session_state.accounts,
        column_config={
            "Account Name": st.column_config.TextColumn("Name"),
            "Balance": st.column_config.NumberColumn("Balance", format="%.2f"),
            "Currency": st.column_config.SelectboxColumn("Currency", options=['INR', 'USD']),
            "Type": st.column_config.SelectboxColumn("Type", options=['Bank/Cash', 'Investment (Non-Zerodha)', 'Credit Card'], required=True, 
                                                help="For Manual Assets (RSU, PPF, Gold). Do NOT add Zerodha stocks here (they are auto-added). NOTE: Loans should be entered in Financial Obligations section.")
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="accounts_editor_v5",
        on_change=save_all_data_callback
    )
    st.session_state.accounts = edited_accounts

# 3. 🏠 Core Data
with st.sidebar.expander("🏠 Fixed Living Costs", expanded=False):
    fixed_costs = st.data_editor(
        st.session_state.fixed_costs,
        column_config={
            "Category": st.column_config.TextColumn("Category", required=True, default="General"),
            "Amount": st.column_config.NumberColumn("Amount (₹)", format="₹%.2f", min_value=0.0, default=0.0),
            "Frequency": st.column_config.SelectboxColumn("Frequency", options=['Monthly', 'Quarterly', 'Half-Yearly', 'Yearly'], required=True, default="Monthly")
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="sidebar_fixed_costs_editor_v5",
        on_change=save_all_data_callback
    )
    st.session_state.fixed_costs = fixed_costs

with st.sidebar.expander("💳 Financial Obligations", expanded=False):
    st.info("💡 **Includes**: Loans, EMIs, SIPs, Term/Health Insurance premiums, or any other recurring monthly commitment.")
    obligations = st.data_editor(
        st.session_state.obligations,
        column_config={
            "Name": st.column_config.TextColumn("Description"),
            "Amount": st.column_config.NumberColumn("Monthly Value (₹)", format="₹%.2f", min_value=0.0),
            "Type": st.column_config.SelectboxColumn("Type", options=['Loan', 'SIP', 'Insurance', 'Other']),
            "Current Balance": st.column_config.NumberColumn("Remaining Principal / Goal", format="₹%.2f", min_value=0.0, help="For loans: Remaining principal. For SIPs: Target or current value."),
            "Currency": st.column_config.SelectboxColumn("Currency", options=['INR', 'USD']),
            "Interest Rate (%)": st.column_config.NumberColumn("Interest/Yield (%)", format="%.1f%%", min_value=0.0)
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="sidebar_obligations_editor_v5",
        on_change=save_all_data_callback
    )
    st.session_state.obligations = obligations

with st.sidebar.expander("🏠 Illiquid Assets", expanded=False):
    illiquid_assets = st.data_editor(
        st.session_state.illiquid_assets,
        column_config={
            "Asset Type": st.column_config.SelectboxColumn("Asset Type", options=["real_estate", "epf", "ppf", "nps", "other"]),
            "Name": st.column_config.TextColumn("Name", required=True),
            "Estimated Value": st.column_config.NumberColumn("Estimated Value (₹)", format="₹%.2f", min_value=0.0),
            "Loan Outstanding": st.column_config.NumberColumn("Loan Outstanding (₹)", format="₹%.2f", min_value=0.0),
            "Notes": st.column_config.TextColumn("Notes"),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="sidebar_illiquid_editor_v1",
        on_change=save_all_data_callback,
    )
    st.session_state.illiquid_assets = illiquid_assets

with st.sidebar.expander("💳 Credit Cards", expanded=False):
    credit_cards = st.data_editor(
        st.session_state.credit_cards,
        column_config={
            "Card Name": st.column_config.TextColumn("Card Name", required=True),
            "Credit Limit": st.column_config.NumberColumn("Credit Limit (₹)", format="₹%.2f", min_value=0.0),
            "Current Outstanding": st.column_config.NumberColumn("Outstanding (₹)", format="₹%.2f", min_value=0.0),
            "Billing Date": st.column_config.NumberColumn("Billing Date", min_value=1, max_value=31, step=1),
            "Payment Due Date": st.column_config.NumberColumn("Due Date", min_value=1, max_value=31, step=1),
            "APR (%)": st.column_config.NumberColumn("APR (%)", min_value=0.0, max_value=100.0, format="%.2f"),
            "Min Due Amount": st.column_config.NumberColumn("Min Due (₹)", format="₹%.2f", min_value=0.0),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="sidebar_credit_cards_editor_v1",
        on_change=save_all_data_callback,
    )
    st.session_state.credit_cards = credit_cards

# 5. ➕ Quick Entry
with st.sidebar.expander("➕ Quick Entry", expanded=False):
    # Tabbed approach for cleaner Quick Entry
    entry_tab1, entry_tab2, entry_tab3 = st.tabs(["💰 Expense", "🏦 Account", "📈 Asset"])
    
    with entry_tab1:
        st.markdown("#### Quick Add Transaction")
        # Removed st.form to prevent double-rerun clearing issue
        s_date = st.date_input("Date", value=datetime.now().date(), key="sb_txn_date")
        s_desc = st.text_input("Description", placeholder="Coffee, Rent, etc.", key="sb_txn_desc")
        s_amount = st.number_input("Amount", step=100.0, format="%.2f", key="sb_txn_amt")
        s_cat = st.selectbox("Category", options=CATEGORIES, key="sb_txn_cat")
        
        if st.button("Add Transaction", use_container_width=True, key="sb_txn_btn"):
            if s_desc:
                try:
                    new_txn = pd.DataFrame([{
                        'Date': pd.Timestamp(s_date),
                        'Description': s_desc,
                        'Amount': s_amount,
                        'Category': s_cat
                    }])
                    st.session_state.expenses = pd.concat([st.session_state.expenses, new_txn], ignore_index=True)
                    db.add_expense(st.session_state.user.id, s_date, s_desc, s_amount, s_cat)
                    st.success("✅ Added")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    with entry_tab2:
        st.markdown("#### Add Bank Account/Cash")
        acc_name = st.text_input("Account Name", placeholder="e.g., HDFC Savings", key="sb_acc_name")
        acc_bal = st.number_input("Initial Balance", min_value=0.0, step=1000.0, key="sb_acc_bal")
        acc_type = st.selectbox("Account Type", options=['Bank/Cash', 'Investment (Non-Zerodha)', 'Credit Card'], key="sb_acc_type")
        acc_curr = st.selectbox("Currency", options=['INR', 'USD'], key="sb_acc_curr")
        
        if st.button("Add Account", use_container_width=True, key="sb_acc_btn"):
            if acc_name:
                new_acc = pd.DataFrame([{
                    'Account Name': acc_name,
                    'Balance': acc_bal,
                    'Type': acc_type,
                    'Currency': acc_curr
                }])
                st.session_state.accounts = pd.concat([st.session_state.accounts, new_acc], ignore_index=True)
                db.sync_accounts(st.session_state.user.id, st.session_state.accounts)
                st.success("✅ Account added")
                st.rerun()

    with entry_tab3:
        st.markdown("#### Add Asset (Stock/RSU/Gold)")
        asset_type = st.selectbox("Type", options=ASSET_TYPES, key="sb_asset_type")
        asset_ticker = st.text_input("Ticker", placeholder="e.g., RELIANCE.NS", key="sb_asset_ticker")
        asset_qty = st.number_input("Quantity", min_value=0.0, step=1.0, format="%.2f", key="sb_asset_qty")
        asset_avg_price = st.number_input("Avg Buy Price (₹)", min_value=0.0, step=10.0, format="%.2f", key="sb_asset_avg")
        
        if st.button("Add Asset", use_container_width=True, key="sb_asset_btn"):
            if asset_ticker and asset_qty > 0:
                new_asset = pd.DataFrame([{
                    'Ticker': asset_ticker.upper(),
                    'Type': asset_type,
                    'Quantity': asset_qty,
                    'Avg_Buy_Price': asset_avg_price
                }])
                st.session_state.investments = pd.concat(
                    [st.session_state.investments, new_asset],
                    ignore_index=True
                )
                db.sync_investments(st.session_state.user.id, st.session_state.investments)
                st.success("✅ Asset added")
                fetch_live_price.clear()
                st.rerun()

# 5. Logout
st.sidebar.markdown('<div style="margin-top: 20vh;"></div>', unsafe_allow_html=True)
if st.sidebar.button("🚪 Logout", use_container_width=True, key="sidebar_logout_absolute_final"):
    handle_logout()

st.sidebar.caption("☁️ WealthOS Cloud Connection Active")

# --- MAIN PAGE - TABBED LAYOUT ---
st.title("WealthOS")
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Transactions", f"{len(st.session_state.expenses):,}")
with m2:
    st.metric("Accounts", f"{len(st.session_state.accounts):,}")
with m3:
    st.metric("Investments", f"{len(st.session_state.investments):,}")
with m4:
    prov = _resolved_llm_provider()
    st.metric("AI provider", prov.title())
st.info(
    "🔒 Privacy notice: your financial data stays in your Supabase project. "
    "Only the minimum required context is sent to AI calls."
)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["📊 Dashboard", "💸 Transactions", "📈 Investments", "🤖 AI Brain", "🧾 Tax", "🛡️ Insurance", "🎯 Goals"])

# ============================================================================
# TAB 1: DASHBOARD (Upgraded with Visuals)
# ============================================================================

with tab1:
    user_id = st.session_state.user.id
    score_cache_key = "freedom_score_cache"
    score_user_key = "freedom_score_cache_user"
    if score_cache_key not in st.session_state or st.session_state.get(score_user_key) != user_id:
        st.session_state[score_cache_key] = calculate_freedom_score(user_id, db.supabase)
        st.session_state[score_user_key] = user_id
    freedom = st.session_state[score_cache_key]
    score_value = int(freedom.get("total_score", 0))
    score_tier = freedom.get("tier", "Building")

    net_worth, liquid_net_worth, total_debt, total_portfolio, true_burn, surplus_margin, surplus, monthly_interest_burn, avg_interest, rsu_real_value, monthly_floor, total_emi, csv_variable_spend, unexpected_needs, illiquid_net = calculate_metrics(
        st.session_state.expenses,
        st.session_state.investments,
        st.session_state.accounts,
    )

    # 30-day Freedom Score sparkline
    score_history = []
    try:
        score_res = (
            db.supabase.table("score_history")
            .select("date,score")
            .eq("user_id", user_id)
            .order("date")
            .execute()
        )
        score_history = score_res.data or []
    except Exception:
        score_history = []
    if score_history:
        score_df = pd.DataFrame(score_history)
        score_df["date"] = pd.to_datetime(score_df["date"], errors="coerce")
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
        score_df = score_df[score_df["date"] >= cutoff].sort_values("date")
        if not score_df.empty:
            st.caption("Freedom Score (30-day trend)")
            st.line_chart(score_df.set_index("date")["score"], height=100)

    # ROW 1 — Hero
    hero_left, hero_right = st.columns([2.2, 1.0])
    with hero_left:
        st.markdown(
            f"<h1 style='margin-bottom:0'>Freedom Score: {score_value}</h1>"
            f"<span class='tier-badge'>{score_tier}</span>",
            unsafe_allow_html=True,
        )
        weights = {
            "savings": 250.0,
            "debt_freedom": 200.0,
            "runway": 200.0,
            "tax_efficiency": 150.0,
            "insurance": 100.0,
            "goals": 100.0,
        }
        labels = {
            "savings": "Savings",
            "debt_freedom": "Debt Freedom",
            "runway": "Runway",
            "tax_efficiency": "Tax Efficiency",
            "insurance": "Insurance",
            "goals": "Goal Progress",
        }
        for key, max_points in weights.items():
            points = float(freedom.get("breakdown", {}).get(key, 0))
            st.progress(min(max(points / max_points, 0.0), 1.0), text=f"{labels[key]}: {int(points)} / {int(max_points)}")

    with hero_right:
        st.metric("Liquid Net Worth", f"₹{liquid_net_worth:,.0f}")
        st.metric("Monthly Surplus", f"₹{surplus:,.0f}")
        runway_months = (liquid_net_worth / true_burn) if true_burn > 0 else 0.0
        st.metric("Runway", f"{runway_months:.1f} months")

    st.divider()

    # ROW 2 — Status strip
    s1, s2, s3, s4 = st.columns(4)
    ef_status = get_ef_status(user_id, db.supabase)
    with s1:
        status_label = ef_status.get("status", "building").upper()
        if status_label == "BUILDING":
            st.error(f"EF: {status_label}")
        elif status_label == "ADEQUATE":
            st.warning(f"EF: {status_label}")
        else:
            st.success(f"EF: {status_label}")
    with s2:
        ded = get_deductions_summary(user_id, current_financial_year(), db.supabase)
        ratio_80c = ded["s80c"]["invested"] / max(float(ded["s80c"]["limit"]), 1.0)
        st.progress(min(ratio_80c, 1.0), text=f"80C: ₹{ded['s80c']['invested']:,.0f} / ₹{ded['s80c']['limit']:,.0f}")
    with s3:
        _, revolving_cost, apr_badges = get_credit_card_intelligence()
        if apr_badges:
            st.error("High-APR debt alert")
            st.caption(f"Revolving cost: ₹{revolving_cost:,.0f}/mo")
        else:
            st.success("No high-APR alert")
    with s4:
        life_audit = audit_life_cover(user_id, db.supabase)
        health_audit = audit_health_cover(user_id, db.supabase)
        life_cov = 1.0 if life_audit["recommended"] <= 0 else min(life_audit["actual"] / life_audit["recommended"], 1.0)
        health_cov = min(health_audit["actual"] / max(health_audit["recommended"], 1.0), 1.0)
        coverage = (life_cov + health_cov) / 2.0
        st.progress(coverage, text=f"Insurance Coverage: {int(coverage * 100)}%")

    st.divider()

    # ROW 3 — Charts
    c_left, c_right = st.columns(2)
    with c_left:
        st.subheader("Spend by Category (30 days)")
        if not st.session_state.expenses.empty:
            exp = st.session_state.expenses.copy()
            exp["Date"] = pd.to_datetime(exp["Date"], errors="coerce")
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
            exp = exp[(exp["Date"] >= cutoff) & (exp["Amount"] < 0)]
            spend = (
                exp.assign(Amount=exp["Amount"].abs())
                .groupby("Category", as_index=False)["Amount"]
                .sum()
                .sort_values("Amount", ascending=False)
            )
            if not spend.empty and PLOTLY_AVAILABLE:
                fig = go.Figure(data=[go.Bar(x=spend["Category"], y=spend["Amount"])])
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            elif not spend.empty:
                st.bar_chart(spend.set_index("Category")["Amount"], height=300)
            else:
                st.info("No expense data in last 30 days.")
    with c_right:
        st.subheader("Net Worth Trend (6 months)")
        if not st.session_state.expenses.empty:
            exp = st.session_state.expenses.copy()
            exp["Date"] = pd.to_datetime(exp["Date"], errors="coerce")
            exp = exp.dropna(subset=["Date"])
            month_idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=6, freq="MS")
            monthly_flow = (
                exp.set_index("Date")
                .groupby(pd.Grouper(freq="MS"))["Amount"]
                .sum()
                .reindex(month_idx, fill_value=0.0)
            )
            start_estimate = liquid_net_worth - float(monthly_flow.sum())
            nw_series = monthly_flow.cumsum() + start_estimate
            trend_df = pd.DataFrame({"month": month_idx, "net_worth": nw_series.values}).set_index("month")
            st.line_chart(trend_df["net_worth"], height=300)
        else:
            st.info("Add transactions to unlock trend chart.")

    st.divider()

    # ROW 4 — AI CFO Chat
    st.subheader("AI CFO Chat")
    if "cfo_chat_messages" not in st.session_state:
        st.session_state.cfo_chat_messages = []

    for msg in st.session_state.cfo_chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for tool_evt in msg.get("tool_events", []):
                with st.expander(f"> Called {tool_evt.get('tool_name', 'tool')}()", expanded=False):
                    st.json(
                        {
                            "arguments": tool_evt.get("arguments", {}),
                            "output": tool_evt.get("output", {}),
                        }
                    )

    prompt = st.chat_input("Ask your CFO anything about your money decisions.")
    if prompt:
        provider = _resolved_llm_provider()
        env_key_name = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }.get(provider, "GEMINI_API_KEY")
        has_key = bool(st.session_state.api_key or _get_secret_or_env(env_key_name))
        if not has_key:
            st.error(f"Missing provider key: {env_key_name}")
        else:
            st.session_state.cfo_chat_messages.append({"role": "user", "content": prompt})
            try:
                with st.spinner("CFO is thinking..."):
                    reply, tool_events = run_agent_with_trace(
                        prompt, user_id, db.supabase, **_llm_runtime_kwargs()
                    )
            except Exception as exc:
                # Drop the orphaned question so the transcript doesn't show it unanswered.
                st.session_state.cfo_chat_messages.pop()
                detail = str(exc)
                if "API_KEY_INVALID" in detail or "API key not valid" in detail:
                    st.error(
                        "The AI provider rejected the API key. Paste a current key into "
                        "AI Settings below, or clear the field to use the app's own key."
                    )
                elif "NOT_FOUND" in detail or "is not found" in detail:
                    st.error(
                        "That model isn't available for this API key. Pick another one in AI Settings."
                    )
                elif any(s in detail for s in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")):
                    st.error(
                        "The AI provider is busy right now — this one is on their side, not yours. "
                        "Wait a few seconds and ask again."
                    )
                else:
                    st.error(f"The AI call failed: {detail[:200]}")
            else:
                st.session_state.cfo_chat_messages.append(
                    {
                        "role": "assistant",
                        "content": reply,
                        "tool_events": tool_events,
                    }
                )
                st.rerun()

    st.divider()

    # ROW 5 — Active Alerts
    st.subheader("Active Alerts")
    alerts = []
    tax_alert = get_80c_alert(user_id, db.supabase)
    if tax_alert:
        alerts.append(("warning", tax_alert))

    for h_alert in get_harvesting_alerts(user_id, db.supabase):
        alerts.append(("warning", h_alert))

    trap_rows = detect_endowment_traps(user_id, db.supabase)
    for trap in trap_rows:
        alerts.append(
            (
                "error",
                f"{trap.get('policy_name', 'Policy')} IRR {trap.get('estimated_irr', 0.0) * 100:.1f}% is below 7%.",
            )
        )

    if life_audit["adequacy"] != "adequate":
        alerts.append(("error", f"Life cover gap: ₹{life_audit['gap']:,.0f}."))
    if health_audit["adequacy"] != "adequate":
        alerts.append(("error", f"Health cover gap: ₹{health_audit['gap']:,.0f}."))

    if not alerts:
        st.success("No active alerts. Keep compounding.")
    else:
        for level, text in alerts:
            if level == "error":
                st.error(text)
            else:
                st.warning(text)

# ============================================================================
# TAB 2: TRANSACTIONS
# ============================================================================

with tab2:
    # --- EMPTY STATE ONBOARDING ---
    if st.session_state.expenses.empty:
        st.info("👋 Welcome! Add your first transaction in Quick Entry menu to see your spending log.")

    st.subheader("Add Transactions")
    ocr_tab2, ocr_tab3 = st.tabs(["PDF Statement", "Manual Entry"])

    with ocr_tab2:
        pdf_file = st.file_uploader(
            "Upload PDF statement",
            type=["pdf"],
            key="ocr_pdf_upload",
        )
        if pdf_file is not None and st.button("Parse PDF", use_container_width=True, key="parse_pdf_btn"):
            with st.spinner("Parsing with AI..."):
                parsed_rows = parse_file(
                    file_bytes=pdf_file.getvalue(),
                    mime_type=pdf_file.type or "application/pdf",
                    user_id=str(st.session_state.user.id),
                    supabase=db.supabase,
                )
                st.session_state.ocr_transactions = parsed_rows
                if parsed_rows:
                    st.success(f"Parsed {len(parsed_rows)} transactions")
                else:
                    st.warning("No transactions found from this PDF.")

    with ocr_tab3:
        with st.form("ocr_manual_txn_form", clear_on_submit=True):
            m_date = st.date_input("Date", value=datetime.now().date(), key="ocr_manual_date")
            m_merchant = st.text_input("Merchant", key="ocr_manual_merchant")
            m_amount = st.number_input("Amount", step=100.0, format="%.2f", key="ocr_manual_amount")
            m_currency = st.text_input("Currency", value="INR", key="ocr_manual_currency")
            m_category = st.selectbox(
                "Category",
                options=["food", "transport", "shopping", "utilities", "entertainment", "health", "income", "other"],
                key="ocr_manual_category",
            )
            if st.form_submit_button("Add to Review List", use_container_width=True):
                if m_merchant.strip():
                    staged = st.session_state.get("ocr_transactions", [])
                    staged.append(
                        {
                            "merchant": m_merchant.strip(),
                            "amount": float(m_amount),
                            "date": m_date.isoformat(),
                            "currency": (m_currency or "INR").upper(),
                            "category": m_category,
                        }
                    )
                    st.session_state.ocr_transactions = staged
                    st.success("Added to review list.")
                else:
                    st.warning("Please enter merchant name.")

    staged_transactions = st.session_state.get("ocr_transactions", [])
    if staged_transactions:
        st.markdown("#### Review Parsed Transactions")
        review_df = pd.DataFrame(staged_transactions)
        edited_review = st.data_editor(
            review_df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "merchant": st.column_config.TextColumn("Merchant"),
                "amount": st.column_config.NumberColumn("Amount", format="%.2f"),
                "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                "currency": st.column_config.TextColumn("Currency"),
                "category": st.column_config.SelectboxColumn(
                    "Category",
                    options=["food", "transport", "shopping", "utilities", "entertainment", "health", "income", "other"],
                ),
            },
            hide_index=True,
            key="ocr_review_editor",
        )

        confirm_col, clear_col = st.columns(2)
        with confirm_col:
            if st.button("Confirm & Save", type="primary", use_container_width=True, key="ocr_confirm_save"):
                try:
                    count = confirm_and_save(
                        transactions=edited_review.to_dict(orient="records"),
                        user_id=str(st.session_state.user.id),
                        supabase=db.supabase,
                    )
                    st.success(f"Saved {count} OCR transactions.")
                    st.session_state.ocr_transactions = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save OCR transactions: {e}")
        with clear_col:
            if st.button("Clear OCR Review", use_container_width=True, key="ocr_clear_review"):
                st.session_state.ocr_transactions = []
                st.rerun()

    st.divider()
    
    # --- CSV UPLOADER (MOBILE UX) ---
    with st.expander("📤 Import Bank Statement (CSV)", expanded=False):
        tmpl = "date,description,amount,category\n2026-01-15,Sample purchase,-250.50,Needs\n2026-01-16,Salary credit,120000,Income\n"
        st.caption(
            "Expected: a header row with **date** and **amount** (or debit/credit). "
            "Semicolon or tab separators are OK. UTF-8 or Excel-exported CSV supported."
        )
        st.download_button(
            "Download example CSV",
            data=tmpl,
            file_name="wealthos_transactions_sample.csv",
            mime="text/csv",
            use_container_width=True,
            key="tab2_csv_template_dl",
        )
        uploaded_file = st.file_uploader(
            "Upload Bank Statement",
            type=['csv'],
            help="Supports Indian bank CSVs",
            key="tab2_csv_uploader"
        )
        if uploaded_file is not None:
            if st.button("Parse CSV", use_container_width=True):
                with st.spinner("Parsing..."):
                    parsed = parse_bank_csv(uploaded_file)
                    if parsed is not None and not parsed.empty:
                        st.session_state.parsed_csv = parsed
                        st.success(f"Found {len(parsed)} transactions")
                    else:
                        st.error("No valid transactions found")

    # Search and Filter
    search_term = st.text_input("🔍 Search Transactions", placeholder="Search by Description or Category...")
    
    # Action Buttons
    btn1, btn2, btn3 = st.columns([3, 1, 1])
    with btn1:
        pass  # Empty space for search
    with btn2:
        if st.button("🔥 Sort by Amount", use_container_width=True):
            if not st.session_state.expenses.empty:
                # Sort by absolute magnitude (high-magnitude sorting)
                st.session_state.expenses = st.session_state.expenses.reindex(
                    st.session_state.expenses.Amount.abs().sort_values(ascending=False).index
                )
                if save_expenses(st.session_state.expenses):
                    st.success("Sorted by Magnitude (Impact)")
                    st.rerun()
    with btn3:
        if st.button("📅 Sort by Recent", use_container_width=True):
            if not st.session_state.expenses.empty:
                st.session_state.expenses = st.session_state.expenses.sort_values('Date', ascending=False)
                if save_expenses(st.session_state.expenses):
                    st.success("Sorted by Date")
                    st.rerun()
    
    st.divider()
    
    # CSV Preview Section
    if st.session_state.parsed_csv is not None:
        st.subheader("📥 CSV Preview")
        st.write(f"**{len(st.session_state.parsed_csv)} transactions ready to import**")
        st.dataframe(
            st.session_state.parsed_csv.head(10),
            use_container_width=True,
            hide_index=True
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Merge to Database", type="primary", use_container_width=True):
                unique_new = deduplicate_transactions(
                    st.session_state.parsed_csv,
                    st.session_state.expenses
                )
                if unique_new.empty:
                    st.warning("All transactions already exist")
                else:
                    try:
                        # Batch Sync to Supabase
                        user_id = st.session_state.user.id
                        for _, row in unique_new.iterrows():
                            db.add_expense(user_id, row['Date'], row['Description'], row['Amount'], row['Category'])
                        
                        st.session_state.expenses = pd.concat(
                            [st.session_state.expenses, unique_new],
                            ignore_index=True
                        )
                        st.success(f"✅ Added {len(unique_new)} transactions to cloud")
                        st.session_state.parsed_csv = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to sync transactions: {e}")
        with col2:
            if st.button("Clear Preview", use_container_width=True):
                st.session_state.parsed_csv = None
                st.rerun()
        
        st.divider()
    
    # Auto-Categorize Section
    st.subheader("⚡ Auto-Categorize")
    
    # Teach Mode UI
    with st.expander("🧠 Teach WealthOS"):
        teach_keyword = st.text_input("If description contains...", placeholder="e.g., Landlord Name")
        teach_category = st.selectbox("Mark as...", options=CATEGORIES)
        if st.button("Add Rule", use_container_width=True):
            if teach_keyword.strip():
                if save_user_rule(teach_keyword.strip(), teach_category):
                    st.success(f"✅ Rule added: '{teach_keyword}' → {teach_category}")
                    st.rerun()
                else:
                    st.error("❌ Failed to save rule")
            else:
                st.warning("⚠️ Please enter a keyword")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        force_overwrite = st.checkbox("Force Overwrite", help="Overwrite manually set categories")
    with col2:
        if st.button("Run", use_container_width=True):
            if st.session_state.expenses.empty:
                st.warning("No transactions to categorize")
            else:
                updated_df, changes = auto_categorize(st.session_state.expenses, force_overwrite)
                if changes > 0:
                    try:
                        user_id = st.session_state.user.id
                        # Clear and Replace strategy for categorizer
                        db.supabase.table("expenses").delete().eq("user_id", user_id).execute()
                        payload = []
                        for _, row in updated_df.iterrows():
                            payload.append({
                                "user_id": user_id,
                                "date": row["Date"].isoformat(),
                                "description": row["Description"],
                                "amount": float(row["Amount"]),
                                "category": row["Category"]
                            })
                        if payload:
                            for i in range(0, len(payload), 500):
                                db.supabase.table("expenses").insert(payload[i:i+500]).execute()
                        
                        st.session_state.expenses = updated_df
                        st.toast(f"✅ Categorized {changes} transactions in cloud!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to sync categorizations: {e}")
                else:
                    st.info("No changes needed")
    
    with st.expander("ℹ️ Active Rules"):
        st.markdown("**Income:** Amount > 0")
        st.markdown("**UPI:** Amount < 0 AND contains 'UPI' → Needs + (Verify)")
        for cat, keywords in KEYWORD_RULES.items():
            st.markdown(f"**{cat}:** {', '.join(keywords)}")
    
    st.divider()
    
    # Transaction Table
    st.subheader("Transaction Log")
    
    if not st.session_state.expenses.empty:
        display_df = st.session_state.expenses.copy()
        if 'Date' in display_df.columns:
            display_df['Date'] = pd.to_datetime(display_df['Date'], errors='coerce')
        
        # Apply search filter if provided
        if search_term:
            mask = (display_df['Description'].str.contains(search_term, case=False, na=False) | 
                   display_df['Category'].str.contains(search_term, case=False, na=False))
            display_df = display_df[mask]
        
        display_df = display_df.sort_values('Date', ascending=False).reset_index(drop=True)
        
        edited_df = st.data_editor(
            display_df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                'Date': st.column_config.DateColumn('Date', format="DD/MM/YYYY"),
                'Description': st.column_config.TextColumn('Description', width="large"),
                'Amount': st.column_config.NumberColumn('Amount', format="₹%.2f"),
                'Category': st.column_config.SelectboxColumn('Category', options=CATEGORIES, required=True)
            },
            hide_index=True,
            key="main_txn_editor"
        )
        
        if st.button("Save Changes", type="primary", key="save_transactions"):
            if 'Date' in edited_df.columns:
                edited_df['Date'] = pd.to_datetime(edited_df['Date'], errors='coerce')
            
            try:
                user_id = st.session_state.user.id
                # Clear and Replace strategy for expenses table sync
                db.supabase.table("expenses").delete().eq("user_id", user_id).execute()
                payload = []
                for _, row in edited_df.iterrows():
                    payload.append({
                        "user_id": user_id,
                        "date": row["Date"].isoformat(),
                        "description": row["Description"],
                        "amount": float(row["Amount"]),
                        "category": row["Category"]
                    })
                if payload:
                    # Supabase handles batching
                    for i in range(0, len(payload), 500):
                        db.supabase.table("expenses").insert(payload[i:i+500]).execute()
                
                st.session_state.expenses = edited_df
                st.success("✅ Changes synced to cloud!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to sync changes: {e}")
    else:
        st.info("No transactions yet. Import a bank statement using the sidebar.")

# ============================================================================
# TAB 3: INVESTMENTS
# ============================================================================

with tab3:
    # --- EMPTY STATE ONBOARDING ---
    if st.session_state.investments.empty:
        st.info("📈 Your portfolio is empty. Add an asset to start tracking your wealth.")
    
    # --- ZERODHA IMPORT UI ---
    st.markdown("### 📥 Import Portfolio")
    with st.expander("Import from Zerodha Console"):
        st.caption("Download your Holdings CSV/XLSX from Zerodha Console -> Portfolio -> Holdings")
        z_file = st.file_uploader("Upload Zerodha File", type=['csv', 'xlsx'], key="z_upload")
        
        if z_file:
            z_df = parse_zerodha_file(z_file)
            if z_df is not None:
                st.dataframe(z_df.head(), use_container_width=True)
                
                col_z1, col_z2 = st.columns(2)
                
                # OPTION A: APPEND (Safe for mixed portfolios)
                if col_z1.button("Merge (Append/Update)", use_container_width=True):
                    # Concatenate and drop duplicates based on Ticker
                    combined = pd.concat([st.session_state.investments, z_df])
                    # Keep the LAST occurrence (the new one)
                    st.session_state.investments = combined.drop_duplicates(subset=['Ticker'], keep='last')
                    # Sync to Supabase
                    db.sync_investments(st.session_state.user.id, st.session_state.investments)
                    st.success("✅ Portfolio merged to cloud!")
                    fetch_live_price.clear()
                    st.rerun()

                # OPTION B: REPLACE STOCKS ONLY (Smart Sync)
                if col_z2.button("Replace Stocks Only", help="Deletes old Stocks/ETFs, keeps Crypto/Gold", use_container_width=True):
                    # Keep non-stock assets (like manual Crypto entries)
                    current = st.session_state.investments
                    preserved = current[~current['Type'].isin(['Stock', 'ETF'])] 
                    
                    # Combine preserved assets with new Zerodha import
                    new_state = pd.concat([preserved, z_df])
                    st.session_state.investments = new_state
                    # Sync to Supabase
                    db.sync_investments(st.session_state.user.id, st.session_state.investments)
                    st.success("✅ Stocks replaced in cloud! Crypto/Gold preserved.")
                    fetch_live_price.clear()
                    st.rerun()
    
    st.divider()
    # --- END ZERODHA UI ---

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("Portfolio")
    with col2:
        if st.button("🔄 Refresh Prices", use_container_width=True):
            fetch_live_price.clear()
            st.rerun()
    
    if not st.session_state.investments.empty:
        portfolio = get_portfolio_with_prices(st.session_state.investments)
        
        if not portfolio.empty:
            total_value = portfolio['Current_Value'].sum()
            total_pl = portfolio['Unrealized_PL'].sum()
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Portfolio Value", f"₹{total_value:,.2f}")
            with col2:
                pl_color = "green" if total_pl >= 0 else "red"
                st.metric("Total Unrealized P/L", f"₹{total_pl:,.2f}")
            
            st.divider()
            
            # Format portfolio for display
            display_portfolio = portfolio.copy()
            display_portfolio = display_portfolio.reset_index(drop=True)
            display_portfolio = display_portfolio.rename(columns={
                'Ticker': 'Ticker',
                'Type': 'Type',
                'Quantity': 'Qty',
                'Avg_Buy_Price': 'Avg Price',
                'Live_Price': 'Live Price',
                'Current_Value': 'Value',
                'Unrealized_PL': 'P/L'
            })
            
            # Style P/L column
            def color_pl(val):
                color = 'green' if val >= 0 else 'red'
                return f'color: {color}'
            
            styled_df = display_portfolio.style.map(
                color_pl,
                subset=['P/L']
            ).format({
                'Avg Price': '₹{:.2f}',
                'Live Price': '₹{:.2f}',
                'Value': '₹{:.2f}',
                'P/L': '₹{:.2f}',
                'Qty': '{:.2f}'
            })
            
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            
            st.divider()
            
            # Edit investments
            st.subheader("Edit Holdings")
            edited_inv = st.data_editor(
                st.session_state.investments,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    'Ticker': st.column_config.TextColumn('Ticker'),
                    'Type': st.column_config.SelectboxColumn('Type', options=ASSET_TYPES),
                    'Quantity': st.column_config.NumberColumn('Quantity', format="%.2f"),
                    'Avg_Buy_Price': st.column_config.NumberColumn('Avg Buy Price', format="₹%.2f")
                },
                hide_index=True,
                key="investment_editor"
            )
            
            if st.button("Save Holdings", type="primary", key="save_investments"):
                st.session_state.investments = edited_inv
                # Sync to Supabase
                db.sync_investments(st.session_state.user.id, st.session_state.investments)
                st.success("✅ Holdings synced to cloud")
                fetch_live_price.clear()
                st.rerun()
    else:
        st.info("No investments yet. Add assets using the sidebar.")

# ============================================================================
# ============================================================================
# TAB 4: AI BRAIN (Fixed & Robust)
# ============================================================================

with tab4:
    st.header("🤖 WealthOS Consultant")
    st.caption(
        f"Provider is **{_resolved_llm_provider()}** (set `LLM_PROVIDER` in `.env` to "
        "`gemini`, `openai`, or `anthropic`; the app calls that vendor's API using your sidebar or env API key — "
        "it does not auto-detect from the key text)."
    )
    
    # --- CONNECTION DOCTOR & SETTINGS ---
    with st.expander("🛠️ AI Settings & Status", expanded=False):
        risk_profile, ytr, allocation = profile_risk_details(st.session_state.user_profile)
        risk_system_prompt = (
            f"User profile context: risk_profile={risk_profile}, "
            f"age={st.session_state.user_profile.get('age')}, years_to_retirement={ytr}, "
            f"target_allocation={allocation}."
        )
        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("Check API Access"):
                try:
                    provider = _resolved_llm_provider()
                    call_llm(
                        "Reply with OK.",
                        system_prompt=risk_system_prompt,
                        model=st.session_state.get("selected_model", "gemini-3.8-flash"),
                        api_key=st.session_state.api_key,
                        provider=provider,
                        max_tokens=32,
                    )
                    default_models = {
                        "gemini": ["gemini-3.8-flash"],
                        "openai": ["gpt-4o-mini", "gpt-4o", "o4-mini"],
                        "anthropic": ["claude-sonnet-5"],
                    }
                    models = default_models.get(provider, default_models["gemini"])
                    st.session_state.available_models = models
                    st.success(f"✅ Found {len(models)} models!")
                except Exception as e:
                    st.error(f"Connection Failed: {e}")
        
        with c2:
            # Model Selector persistence (Refactored for Supabase)
            current_model = st.session_state.get('selected_model', 'gemini-3.8-flash')
            opts = st.session_state.get('available_models', ['gemini-3.8-flash'])
            
            new_model = st.selectbox("Select Model", options=opts, index=0 if current_model not in opts else opts.index(current_model))
            if new_model != current_model:
                st.session_state.selected_model = new_model
                db.sync_settings(st.session_state.user.id, st.session_state.salary, st.session_state.api_key, new_model)
                st.toast("✅ Model updated", icon="🤖")

    # --- CHAT INTERFACE ---
    col1, col2 = st.columns([2, 1])
    with col1:
        user_query = st.text_area(
            "Ask the CFO:", 
            placeholder="Examples:\n- Review my debt strategy.\n- Should I invest my surplus or prepay my loan?\n- Analyze my burn rate."
        )
    with col2:
        st.info("💡 The AI analyzes your Net Worth, Surplus, and Debt Interest. No account numbers are shared.")
        
    if st.button("Analyze Finances", type="primary"):
        provider = _resolved_llm_provider()
        env_key_name = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }.get(provider, "GEMINI_API_KEY")
        has_key = bool(st.session_state.api_key or _get_secret_or_env(env_key_name))
        if not has_key:
            st.error(f"Please provide API key for {provider} ({env_key_name}).")
        else:
            with st.spinner("Thinking..."):
                try:
                    response_text = run_agent(
                        user_query,
                        st.session_state.user.id,
                        db.supabase,
                        **_llm_runtime_kwargs(),
                    )
                    
                    st.markdown("### 🧠 CFO Analysis")
                    st.markdown(response_text)
                    
                except Exception as e:
                    if "429" in str(e):
                        st.error("⚠️ Quota Limit Hit. Please wait 30s.")
                    else:
                        st.error(f"Error: {e}")

# ============================================================================
# TAB 5: TAX ENGINE
# ============================================================================

with tab5:
    st.header("\U0001F9FE Tax")
    st.info("Not built yet \u2014 this tab is a placeholder for where tax work is headed.")
    st.markdown(
        "**On the roadmap**\n\n"
        "- Old vs new regime compared from your actual salary and declared investments\n"
        "- 80C / 80D / NPS tracked against their limits, showing what is still unused\n"
        "- Capital gains from your holdings, short vs long term, and harvesting opportunities\n"
        "- RSU and ESOP treatment, where most salaried confusion actually lives\n"
        "- An export a CA can work from directly\n\n"
        "The question this tab has to answer before any of it ships: where does useful "
        "tax education end and regulated advice begin? The intent is to explain and hand "
        "off to a CA, not to file on your behalf."
    )


# ============================================================================
# TAB 6: INSURANCE
# ============================================================================

with tab6:
    st.header("\U0001F6E1\uFE0F Insurance")
    st.caption("Rules of thumb for sizing cover \u2014 not advice. Based on the pay in your profile.")

    _annual_income = safe_float(st.session_state.get("salary", 0.0)) * 12
    if _annual_income <= 0:
        st.info("Add your monthly pay from the Profile page and these numbers will fill in.")
    else:
        _life_cover = _annual_income * 10
        _health_cover = max(1000000.0, _annual_income * 0.5)

        _ins_c1, _ins_c2 = st.columns(2)
        with _ins_c1:
            st.metric("Term cover to aim for", f"\u20B9{_life_cover:,.0f}")
            st.caption("Roughly 10x annual income \u2014 the usual starting point if anyone depends on your income.")
        with _ins_c2:
            st.metric("Health cover floor", f"\u20B9{_health_cover:,.0f}")
            st.caption("At least \u20B910L, or half your annual income, whichever is higher.")

        st.divider()
        st.markdown(
            "**Worth checking**\n\n"
            "- Buy a term plan, not an endowment or ULIP. Insurance and investment are both cheaper bought separately.\n"
            "- Cover should last until the people depending on you no longer do, not until a round birthday.\n"
            "- Employer health cover ends with the job. Hold a personal policy alongside it.\n"
            "- Premiums paid count towards 80D, which the Tax tab will pick up once it exists."
        )


# ============================================================================
# TAB 7: GOALS + EF
# ============================================================================

with tab7:
    st.header("🎯 Goals + Emergency Fund")
    st.caption(
        "Fill the emergency fund first, then sequence goals by deadline and priority. "
        "Monthly surplus is allocated top-down, so the nearest goal is funded before the rest."
    )

    ef_status = get_ef_status(st.session_state.user.id, db.supabase)
    ef_col1, ef_col2, ef_col3 = st.columns(3)
    with ef_col1:
        st.metric("EF Target", f"₹{ef_status['target']:,.0f}")
    with ef_col2:
        st.metric("EF Current", f"₹{ef_status['current']:,.0f}")
    with ef_col3:
        st.metric("Months Covered", f"{ef_status['months_covered']:.1f}")

    if ef_status["status"] == "building":
        st.error("BUILDING", icon="🔴")
    elif ef_status["status"] == "adequate":
        st.warning("ADEQUATE", icon="🟠")
    else:
        st.success("STRONG", icon="🟢")

    with st.expander("Emergency Fund Setup", expanded=False):
        with st.form("ef_setup_form"):
            ef_target_months = st.number_input(
                "Target Months",
                min_value=1,
                max_value=24,
                value=int(st.session_state.emergency_fund.get("Target Months", 6)),
            )
            ef_current_amount = st.number_input(
                "Current Amount (₹)",
                min_value=0.0,
                value=float(st.session_state.emergency_fund.get("Current Amount", 0.0)),
                format="%.2f",
            )
            ef_account_name = st.text_input(
                "Account Name",
                value=str(st.session_state.emergency_fund.get("Account Name", "")),
            )
            if st.form_submit_button("Save Emergency Fund", use_container_width=True):
                st.session_state.emergency_fund = {
                    "Target Months": ef_target_months,
                    "Current Amount": ef_current_amount,
                    "Account Name": ef_account_name,
                }
                db.upsert_emergency_fund(st.session_state.user.id, st.session_state.emergency_fund)
                st.success("Emergency fund settings saved.")
                st.rerun()

    st.subheader("Goals")
    edited_goals = st.data_editor(
        st.session_state.goals,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Name": st.column_config.TextColumn("Name", required=True),
            "Goal Type": st.column_config.SelectboxColumn(
                "Goal Type",
                options=[
                    "emergency_fund",
                    "debt_payoff",
                    "house",
                    "education",
                    "retirement",
                    "vehicle",
                    "parents_corpus",
                    "travel",
                    "other",
                ],
                required=True,
            ),
            "Target Amount": st.column_config.NumberColumn("Target Amount (₹)", format="₹%.2f", min_value=0.0),
            "Target Date": st.column_config.DateColumn("Target Date", format="YYYY-MM-DD"),
            "Current Amount": st.column_config.NumberColumn("Current Amount (₹)", format="₹%.2f", min_value=0.0),
            "Priority": st.column_config.NumberColumn("Priority (1=highest)", min_value=1, max_value=10, step=1),
            "Ring Fenced": st.column_config.CheckboxColumn("Ring-Fenced"),
            "Recommended Instrument": st.column_config.TextColumn("Recommended Instrument"),
            "Notes": st.column_config.TextColumn("Notes"),
        },
        hide_index=True,
        key="goals_editor",
    )
    # Reorderable behavior via priority column edits.
    if not edited_goals.empty:
        edited_goals = edited_goals.sort_values("Priority", ascending=True).reset_index(drop=True)
    st.session_state.goals = edited_goals

    if st.button("Save Goals", type="primary", use_container_width=True, key="save_goals"):
        db.sync_goals(st.session_state.user.id, st.session_state.goals)
        st.success("Goals saved.")
        st.rerun()

    st.subheader("This Month Surplus Plan")
    salary = safe_float(st.session_state.get("salary", 0.0))
    _, _, _, _, true_burn, _, surplus, _, _, _, _, _, _, _, _ = calculate_metrics(
        st.session_state.expenses,
        st.session_state.investments,
        st.session_state.accounts,
    )
    st.caption(f"Monthly surplus used for planning: ₹{surplus:,.0f}")
    plan = allocate_surplus(st.session_state.user.id, surplus, db.supabase)
    st.dataframe(pd.DataFrame(plan), use_container_width=True, hide_index=True)


# ============================================================================
# FOOTER
# ============================================================================

st.divider()
st.caption("WealthOS • Built with Streamlit")
