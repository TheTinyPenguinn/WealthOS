import streamlit as st
import pandas as pd
from supabase import create_client, Client  # <--- FIXED THIS LINE
from decimal import Decimal
from datetime import datetime
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import re
import os
import time
from pathlib import Path


def _load_local_env():
    """
    Lightweight .env loader so Streamlit runs work even when the shell
    did not `source .env` first.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # Non-fatal; env can still be provided by shell/secrets.
        pass


_load_local_env()

def _get_secret_or_env(key: str) -> str:
    env_value = str(os.getenv(key, "")).strip()
    if env_value:
        return env_value
    try:
        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""

def _safe_int(value, default=1):
    try:
        if value is None or pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default

# Initialize Supabase client
@st.cache_resource
def get_supabase_client():
    url = _get_secret_or_env("SUPABASE_URL")
    key = _get_secret_or_env("SUPABASE_ANON_KEY") or _get_secret_or_env("SUPABASE_SERVICE_ROLE_KEY")
    
    if not url or not key:
        st.error("Missing Supabase credentials.")
        st.info("Set SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_SERVICE_ROLE_KEY) via env vars or secrets.toml.")
        st.stop()
        
    try:
        # Create client with cleaned strings
        client = create_client(url, key)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Supabase client: {e}")
        st.stop()

# Initialize client with retry for Streamlit Cloud environment
def get_supabase_client_with_retry():
    """Initialize Supabase client with retry logic for Streamlit Cloud environment issues."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return get_supabase_client()
        except Exception as e:
            if attempt == max_retries - 1:
                st.error(f"Failed to initialize Supabase after {max_retries} attempts: {e}")
                st.stop()
            else:
                st.warning(f"Attempt {attempt + 1}/{max_retries} failed, retrying...")
    return None

supabase = get_supabase_client_with_retry()

def signup_user(email: str, password: str):
    """
    Create an account through Supabase's ordinary public sign-up.

    Uses this app's anon key, so no service-role credential is needed at
    runtime. Requires 'Confirm email' to be OFF in the Supabase project:
    the built-in mailer only delivers to project members and caps sends at
    roughly 2/hour, so a confirmation round trip cannot work here. Every new
    account still only sees its own rows, which row-level security enforces.
    """
    res = supabase.auth.sign_up({"email": email, "password": password})
    if getattr(res, "session", None) is None:
        raise RuntimeError(
            "Account created but it needs email confirmation, and this project "
            "cannot reliably send that mail. Turn off 'Confirm email' in Supabase "
            "under Authentication - Sign In / Providers - Email, then sign up again."
        )
    return res


def ensure_dataframe_schema(df, columns, types=None):
    """Ensure dataframe has correct columns and types, stripping timezones and converting Decimals."""
    if df is None or (isinstance(df, list) and len(df) == 0) or (isinstance(df, pd.DataFrame) and df.empty):
        return pd.DataFrame(columns=columns)
    
    if isinstance(df, list):
        df = pd.DataFrame(df)
    
    # 1. Convert Decimals to float
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, Decimal)).any():
            df[col] = df[col].apply(lambda x: float(x) if isinstance(x, Decimal) else x)
    
    # 2. Timezone Fix (Make Naive)
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
    
    # Ensure all required columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = None
            
    return df[columns]

def load_all_data(user_id):
    """Fetch all tables from Supabase and map to WealthOS internal schema."""
    try:
        # Load User Settings
        settings_res = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
        if not settings_res.data:
            # New user handling
            default_settings = {"user_id": user_id, "salary": 0.0, "api_key": "", "selected_model": "gemini-3.8-flash"}
            supabase.table("user_settings").insert(default_settings).execute()
            settings = default_settings
        else:
            settings = settings_res.data[0]

        # Load Accounts
        acc_res = supabase.table("accounts").select("*").eq("user_id", user_id).execute()
        accounts = ensure_dataframe_schema(acc_res.data, ["name", "balance", "currency", "type"])
        accounts = accounts.rename(columns={"name": "Account Name", "balance": "Balance", "currency": "Currency", "type": "Type"})

        # Load Fixed Costs
        fixed_res = supabase.table("fixed_costs").select("*").eq("user_id", user_id).execute()
        fixed_costs = ensure_dataframe_schema(fixed_res.data, ["category", "amount", "frequency"])
        fixed_costs = fixed_costs.rename(columns={"category": "Category", "amount": "Amount", "frequency": "Frequency"})

        # Load Obligations
        obl_res = supabase.table("obligations").select("*").eq("user_id", user_id).execute()
        obligations = ensure_dataframe_schema(obl_res.data, ["name", "monthly_emi", "type", "current_balance", "currency", "interest_rate"])
        obligations = obligations.rename(columns={
            "monthly_emi": "Amount", 
            "interest_rate": "Interest Rate (%)", 
            "current_balance": "Current Balance",
            "name": "Name",
            "type": "Type",
            "currency": "Currency"
        })

        # Load Investments
        inv_res = supabase.table("investments").select("*").eq("user_id", user_id).execute()
        investments = ensure_dataframe_schema(inv_res.data, ["ticker", "type", "quantity", "avg_buy_price"])
        investments = investments.rename(columns={
            "ticker": "Ticker",
            "type": "Type",
            "quantity": "Quantity",
            "avg_buy_price": "Avg_Buy_Price"
        })

        # Load Expenses
        exp_res = supabase.table("expenses").select("*").eq("user_id", user_id).execute()
        expenses = ensure_dataframe_schema(exp_res.data, ["date", "description", "amount", "category"])
        expenses = expenses.rename(columns={
            "date": "Date",
            "description": "Description",
            "amount": "Amount",
            "category": "Category"
        })
        if not expenses.empty:
            expenses["Date"] = pd.to_datetime(expenses["Date"]).dt.tz_localize(None)

        # Load Illiquid Assets (optional in older schemas)
        try:
            illiquid_res = supabase.table("illiquid_assets").select("*").eq("user_id", user_id).execute()
            illiquid_assets = ensure_dataframe_schema(
                illiquid_res.data,
                ["asset_type", "name", "estimated_value", "loan_outstanding", "notes"],
            )
            illiquid_assets = illiquid_assets.rename(
                columns={
                    "asset_type": "Asset Type",
                    "name": "Name",
                    "estimated_value": "Estimated Value",
                    "loan_outstanding": "Loan Outstanding",
                    "notes": "Notes",
                }
            )
        except Exception:
            illiquid_assets = pd.DataFrame(columns=["Asset Type", "Name", "Estimated Value", "Loan Outstanding", "Notes"])

        # Load Credit Cards (optional in older schemas)
        try:
            cards_res = supabase.table("credit_cards").select("*").eq("user_id", user_id).execute()
            credit_cards = ensure_dataframe_schema(
                cards_res.data,
                [
                    "card_name",
                    "credit_limit",
                    "current_outstanding",
                    "billing_date",
                    "payment_due_date",
                    "apr_percent",
                    "min_due_amount",
                ],
            )
            credit_cards = credit_cards.rename(
                columns={
                    "card_name": "Card Name",
                    "credit_limit": "Credit Limit",
                    "current_outstanding": "Current Outstanding",
                    "billing_date": "Billing Date",
                    "payment_due_date": "Payment Due Date",
                    "apr_percent": "APR (%)",
                    "min_due_amount": "Min Due Amount",
                }
            )
        except Exception:
            credit_cards = pd.DataFrame(
                columns=["Card Name", "Credit Limit", "Current Outstanding", "Billing Date", "Payment Due Date", "APR (%)", "Min Due Amount"]
            )

        # Load User Profile (optional in older schemas)
        try:
            profile_res = supabase.table("user_profile").select("*").eq("user_id", user_id).limit(1).execute()
            user_profile = profile_res.data[0] if profile_res.data else {}
        except Exception:
            user_profile = {}

        # Load Capital Gains (optional in older schemas)
        try:
            cg_res = supabase.table("capital_gains").select("*").eq("user_id", user_id).execute()
            capital_gains = ensure_dataframe_schema(
                cg_res.data,
                [
                    "asset_name",
                    "asset_type",
                    "buy_date",
                    "buy_price",
                    "sell_date",
                    "sell_price",
                    "units",
                    "notes",
                ],
            )
            capital_gains = capital_gains.rename(
                columns={
                    "asset_name": "Asset Name",
                    "asset_type": "Asset Type",
                    "buy_date": "Buy Date",
                    "buy_price": "Buy Price",
                    "sell_date": "Sell Date",
                    "sell_price": "Sell Price",
                    "units": "Units",
                    "notes": "Notes",
                }
            )
            if not capital_gains.empty:
                capital_gains["Buy Date"] = pd.to_datetime(capital_gains["Buy Date"], errors="coerce")
                capital_gains["Sell Date"] = pd.to_datetime(capital_gains["Sell Date"], errors="coerce")
        except Exception:
            capital_gains = pd.DataFrame(
                columns=["Asset Name", "Asset Type", "Buy Date", "Buy Price", "Sell Date", "Sell Price", "Units", "Notes"]
            )

        # Load Insurance Policies (optional in older schemas)
        try:
            ins_res = supabase.table("insurance_policies").select("*").eq("user_id", user_id).execute()
            insurance_policies = ensure_dataframe_schema(
                ins_res.data,
                [
                    "policy_name",
                    "policy_type",
                    "insurer",
                    "annual_premium",
                    "sum_assured",
                    "maturity_value",
                    "start_date",
                    "maturity_date",
                    "is_active",
                    "notes",
                ],
            )
            insurance_policies = insurance_policies.rename(
                columns={
                    "policy_name": "Policy Name",
                    "policy_type": "Policy Type",
                    "insurer": "Insurer",
                    "annual_premium": "Annual Premium",
                    "sum_assured": "Sum Assured",
                    "maturity_value": "Maturity Value",
                    "start_date": "Start Date",
                    "maturity_date": "Maturity Date",
                    "is_active": "Is Active",
                    "notes": "Notes",
                }
            )
            if not insurance_policies.empty:
                insurance_policies["Start Date"] = pd.to_datetime(insurance_policies["Start Date"], errors="coerce")
                insurance_policies["Maturity Date"] = pd.to_datetime(insurance_policies["Maturity Date"], errors="coerce")
        except Exception:
            insurance_policies = pd.DataFrame(
                columns=["Policy Name", "Policy Type", "Insurer", "Annual Premium", "Sum Assured", "Maturity Value", "Start Date", "Maturity Date", "Is Active", "Notes"]
            )

        # Load Emergency Fund (optional in older schemas)
        try:
            ef_res = supabase.table("emergency_fund").select("*").eq("user_id", user_id).limit(1).execute()
            if ef_res.data:
                ef_row = ef_res.data[0]
                emergency_fund = {
                    "Target Months": int(ef_row.get("target_months") or 6),
                    "Current Amount": float(ef_row.get("current_amount") or 0.0),
                    "Account Name": ef_row.get("account_name", ""),
                }
            else:
                emergency_fund = {"Target Months": 6, "Current Amount": 0.0, "Account Name": ""}
        except Exception:
            emergency_fund = {"Target Months": 6, "Current Amount": 0.0, "Account Name": ""}

        # Load Goals (optional in older schemas)
        try:
            goals_res = supabase.table("goals").select("*").eq("user_id", user_id).order("priority").execute()
            goals = ensure_dataframe_schema(
                goals_res.data,
                [
                    "name",
                    "goal_type",
                    "target_amount",
                    "target_date",
                    "current_amount",
                    "priority",
                    "is_ring_fenced",
                    "recommended_instrument",
                    "notes",
                ],
            )
            goals = goals.rename(
                columns={
                    "name": "Name",
                    "goal_type": "Goal Type",
                    "target_amount": "Target Amount",
                    "target_date": "Target Date",
                    "current_amount": "Current Amount",
                    "priority": "Priority",
                    "is_ring_fenced": "Ring Fenced",
                    "recommended_instrument": "Recommended Instrument",
                    "notes": "Notes",
                }
            )
            if not goals.empty:
                goals["Target Date"] = pd.to_datetime(goals["Target Date"], errors="coerce")
        except Exception:
            goals = pd.DataFrame(
                columns=["Name", "Goal Type", "Target Amount", "Target Date", "Current Amount", "Priority", "Ring Fenced", "Recommended Instrument", "Notes"]
            )

        return {
            "settings": settings,
            "accounts": accounts,
            "fixed_costs": fixed_costs,
            "obligations": obligations,
            "investments": investments,
            "expenses": expenses,
            "illiquid_assets": illiquid_assets,
            "credit_cards": credit_cards,
            "user_profile": user_profile,
            "capital_gains": capital_gains,
            "insurance_policies": insurance_policies,
            "emergency_fund": emergency_fund,
            "goals": goals,
        }
    except Exception as e:
        st.error(f"Error loading database: {e}")
        return None

def sync_accounts(user_id, df):
    """Sync accounts to Supabase. Handles empty dataframes by clearing table."""
    try:
        supabase.table("accounts").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "name": row.get("Account Name", "Unknown"),
                    "balance": float(row.get("Balance", 0.0)),
                    "currency": row.get("Currency", "INR"),
                    "type": row.get("Type", "Bank/Cash")
                })
            if payload:
                supabase.table("accounts").insert(payload).execute()
    except Exception as e:
        st.error(f"Account Sync Error: {e}")

def sync_fixed(user_id, df):
    """Sync fixed costs to Supabase. Handles empty dataframes and enforces non-null constraints."""
    try:
        supabase.table("fixed_costs").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                # Enforce non-null frequency and category
                category = row.get("Category") or "General"
                frequency = row.get("Frequency") or "Monthly"
                amount = float(row.get("Amount") or 0.0)
                
                payload.append({
                    "user_id": user_id,
                    "category": str(category),
                    "amount": amount,
                    "frequency": str(frequency)
                })
            if payload:
                supabase.table("fixed_costs").insert(payload).execute()
    except Exception as e:
        st.error(f"Fixed Costs Sync Error: {e}")

def sync_obligations(user_id, df):
    """Sync obligations to Supabase. Handles empty dataframes."""
    try:
        supabase.table("obligations").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "name": row.get("Name", "Unknown"),
                    "monthly_emi": float(row.get("Amount", 0.0)),
                    "type": row.get("Type", "Loan"),
                    "current_balance": float(row.get("Current Balance", 0.0)),
                    "currency": row.get("Currency", "INR"),
                    "interest_rate": float(row.get("Interest Rate (%)", 0.0))
                })
            if payload:
                supabase.table("obligations").insert(payload).execute()
    except Exception as e:
        st.error(f"Obligations Sync Error: {e}")

def insert_feedback(user_id, feedback_type, message, metadata=None):
    """Log user feedback/bugs into the database."""
    try:
        payload = {
            "user_id": user_id,
            "type": feedback_type,
            "message": message,
            "metadata": metadata or {},
            "created_at": "now()"
        }
        res = supabase.table("feedback").insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"🔍 Debug: Supabase Feedback Error: {str(e)}")
        # If it's a 404, the table likely doesn't exist
        if "404" in str(e):
            st.warning("⚠️ The 'feedback' table might be missing in your Supabase database.")
        return False

def sync_investments(user_id, df):
    """Snapshot Sync for investments to prevent Ghost Assets."""
    supabase.table("investments").delete().eq("user_id", user_id).execute()
    payload = []
    for _, row in df.iterrows():
        payload.append({
            "user_id": user_id,
            "ticker": row["Ticker"],
            "type": row["Type"],
            "quantity": float(row["Quantity"]),
            "avg_buy_price": float(row["Avg_Buy_Price"])
        })
    if payload:
        supabase.table("investments").insert(payload).execute()

def sync_settings(user_id, salary, api_key, model):
    payload = {
        "user_id": user_id,
        "salary": float(salary),
        "api_key": api_key,
        "selected_model": model
    }
    supabase.table("user_settings").upsert(payload, on_conflict="user_id").execute()

def sync_illiquid_assets(user_id, df):
    """Sync illiquid assets table for user."""
    try:
        supabase.table("illiquid_assets").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                payload.append(
                    {
                        "user_id": user_id,
                        "asset_type": str(row.get("Asset Type", "other")),
                        "name": str(row.get("Name", "Unnamed Asset")),
                        "estimated_value": float(row.get("Estimated Value", 0.0)),
                        "loan_outstanding": float(row.get("Loan Outstanding", 0.0)),
                        "notes": str(row.get("Notes", "")),
                    }
                )
            if payload:
                supabase.table("illiquid_assets").insert(payload).execute()
    except Exception as e:
        st.warning(f"Illiquid assets table unavailable; skipped sync. ({e})")

def sync_credit_cards(user_id, df):
    """Sync credit cards table for user."""
    try:
        supabase.table("credit_cards").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                payload.append(
                    {
                        "user_id": user_id,
                        "card_name": str(row.get("Card Name", "Unnamed Card")),
                        "credit_limit": float(row.get("Credit Limit", 0.0)),
                        "current_outstanding": float(row.get("Current Outstanding", 0.0)),
                        "billing_date": _safe_int(row.get("Billing Date", 1), 1),
                        "payment_due_date": _safe_int(row.get("Payment Due Date", 1), 1),
                        "apr_percent": float(row.get("APR (%)", 0.0)),
                        "min_due_amount": float(row.get("Min Due Amount", 0.0)),
                    }
                )
            if payload:
                supabase.table("credit_cards").insert(payload).execute()
    except Exception as e:
        st.warning(f"Credit cards table unavailable; skipped sync. ({e})")

def upsert_user_profile(user_id, profile: dict):
    """Insert/update user profile row. Returns True on success, else False."""
    payload = {
        "user_id": user_id,
        "age": int(profile.get("age", 0)),
        "target_retirement_age": int(profile.get("target_retirement_age", 60)),
        "monthly_income": float(profile.get("monthly_income", 0.0)),
        "income_type": profile.get("income_type", "salaried"),
        "tax_bracket": int(profile.get("tax_bracket", 30)),
        "tax_regime": profile.get("tax_regime", "new"),
    }
    try:
        supabase.table("user_profile").upsert(payload, on_conflict="user_id").execute()
        return True
    except Exception as e:
        # Keep app usable even if Phase-2 table migration is pending.
        st.warning(f"User profile table unavailable; profile saved only for this session. ({e})")
        st.caption(
            "Fix: open Supabase → SQL → run `supabase/migrations/001_wealthos_phase_tables.sql`, "
            "then refresh this app (PostgREST picks up new tables automatically)."
        )
        return False

def load_chat_messages(user_id, limit: int = 50):
    """The most recent CFO chat turns, oldest first.

    Never fatal: if the history table is missing or unreachable the chat simply
    starts empty, exactly as it behaved before history existed.
    """
    try:
        res = (
            supabase.table("cfo_chat_messages")
            .select("role, content, tool_events")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = list(reversed(res.data or []))
    except Exception:
        return []
    return [
        {
            "role": row.get("role") or "assistant",
            "content": row.get("content") or "",
            "tool_events": row.get("tool_events") or [],
        }
        for row in rows
    ]


def save_chat_message(user_id, role: str, content: str, tool_events=None) -> bool:
    """Append one turn. Returns False instead of raising if history is unavailable."""
    import json

    try:
        # tool_events carries whatever the agent produced; force it through JSON
        # so an odd object can never break the insert.
        safe_events = json.loads(json.dumps(tool_events or [], default=str))
    except Exception:
        safe_events = []
    try:
        supabase.table("cfo_chat_messages").insert(
            {
                "user_id": user_id,
                "role": role,
                "content": content or "",
                "tool_events": safe_events,
            }
        ).execute()
        return True
    except Exception:
        return False


def load_tax_investments(user_id, financial_year):
    """Load tax investments for a financial year."""
    try:
        res = (
            supabase.table("tax_investments")
            .select("*")
            .eq("user_id", user_id)
            .eq("financial_year", financial_year)
            .execute()
        )
        source_rows = res.data
    except Exception:
        source_rows = []
    df = ensure_dataframe_schema(source_rows, ["instrument_type", "amount_invested", "notes"])
    return df.rename(
        columns={
            "instrument_type": "Instrument Type",
            "amount_invested": "Amount Invested",
            "notes": "Notes",
        }
    )

def sync_tax_investments(user_id, financial_year, df):
    """Replace tax investments for one FY."""
    try:
        supabase.table("tax_investments").delete().eq("user_id", user_id).eq("financial_year", financial_year).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                payload.append(
                    {
                        "user_id": user_id,
                        "financial_year": financial_year,
                        "instrument_type": str(row.get("Instrument Type", "other_80c")),
                        "amount_invested": float(row.get("Amount Invested", 0.0)),
                        "notes": str(row.get("Notes", "")),
                    }
                )
            if payload:
                supabase.table("tax_investments").insert(payload).execute()
    except Exception as e:
        st.warning(f"Tax Investments table unavailable; skipped sync. ({e})")

def sync_capital_gains(user_id, df):
    """Replace all capital gains positions for user."""
    try:
        supabase.table("capital_gains").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                buy_date = pd.to_datetime(row.get("Buy Date"), errors="coerce")
                sell_date = pd.to_datetime(row.get("Sell Date"), errors="coerce")
                payload.append(
                    {
                        "user_id": user_id,
                        "asset_name": str(row.get("Asset Name", "Unknown Asset")),
                        "asset_type": str(row.get("Asset Type", "other")),
                        "buy_date": buy_date.date().isoformat() if pd.notna(buy_date) else datetime.now().date().isoformat(),
                        "buy_price": float(row.get("Buy Price", 0.0)),
                        "sell_date": sell_date.date().isoformat() if pd.notna(sell_date) else None,
                        "sell_price": float(row.get("Sell Price", 0.0)) if pd.notna(row.get("Sell Price")) else None,
                        "units": float(row.get("Units", 0.0)),
                        "notes": str(row.get("Notes", "")),
                    }
                )
            if payload:
                supabase.table("capital_gains").insert(payload).execute()
    except Exception as e:
        st.warning(f"Capital gains table unavailable; skipped sync. ({e})")

def sync_insurance_policies(user_id, df):
    """Replace insurance inventory for user."""
    try:
        supabase.table("insurance_policies").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                start_date = pd.to_datetime(row.get("Start Date"), errors="coerce")
                maturity_date = pd.to_datetime(row.get("Maturity Date"), errors="coerce")
                payload.append(
                    {
                        "user_id": user_id,
                        "policy_name": str(row.get("Policy Name", "Unknown Policy")),
                        "policy_type": str(row.get("Policy Type", "other")),
                        "insurer": str(row.get("Insurer", "")),
                        "annual_premium": float(row.get("Annual Premium", 0.0)),
                        "sum_assured": float(row.get("Sum Assured", 0.0)) if pd.notna(row.get("Sum Assured")) else None,
                        "maturity_value": float(row.get("Maturity Value", 0.0)) if pd.notna(row.get("Maturity Value")) else None,
                        "start_date": start_date.date().isoformat() if pd.notna(start_date) else None,
                        "maturity_date": maturity_date.date().isoformat() if pd.notna(maturity_date) else None,
                        "is_active": bool(row.get("Is Active", True)),
                        "notes": str(row.get("Notes", "")),
                    }
                )
            if payload:
                supabase.table("insurance_policies").insert(payload).execute()
    except Exception as e:
        st.warning(f"Insurance policies table unavailable; skipped sync. ({e})")

def upsert_emergency_fund(user_id, ef: dict):
    payload = {
        "user_id": user_id,
        "target_months": int(ef.get("Target Months", 6)),
        "current_amount": float(ef.get("Current Amount", 0.0)),
        "account_name": str(ef.get("Account Name", "")),
    }
    try:
        supabase.table("emergency_fund").upsert(payload, on_conflict="user_id").execute()
    except Exception as e:
        st.warning(f"Emergency fund table unavailable; skipped save. ({e})")

def sync_goals(user_id, df):
    """Replace goal list for user."""
    try:
        supabase.table("goals").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                td = pd.to_datetime(row.get("Target Date"), errors="coerce")
                payload.append(
                    {
                        "user_id": user_id,
                        "name": str(row.get("Name", "Goal")),
                        "goal_type": str(row.get("Goal Type", "other")),
                        "target_amount": float(row.get("Target Amount", 0.0)),
                        "target_date": td.date().isoformat() if pd.notna(td) else datetime.now().date().isoformat(),
                        "current_amount": float(row.get("Current Amount", 0.0)),
                        "priority": int(_safe_int(row.get("Priority", 5), 5)),
                        "is_ring_fenced": bool(row.get("Ring Fenced", False)),
                        "recommended_instrument": str(row.get("Recommended Instrument", "")),
                        "notes": str(row.get("Notes", "")),
                    }
                )
            if payload:
                supabase.table("goals").insert(payload).execute()
    except Exception as e:
        st.warning(f"Goals table unavailable; skipped sync. ({e})")

def add_expense(user_id, date, desc, amount, category):
    payload = {
        "user_id": user_id,
        "date": date.isoformat(),
        "description": desc,
        "amount": float(amount),
        "category": category
    }
    supabase.table("expenses").insert(payload).execute()
