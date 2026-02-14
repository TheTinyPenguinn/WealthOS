import streamlit as st
import pandas as pd
from supabase import create_client, Client
from decimal import Decimal

# Initialize Supabase client
@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = get_supabase_client()

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
            default_settings = {"user_id": user_id, "salary": 0.0, "api_key": "", "selected_model": "gemini-1.5-flash"}
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

        return {
            "settings": settings,
            "accounts": accounts,
            "fixed_costs": fixed_costs,
            "obligations": obligations,
            "investments": investments,
            "expenses": expenses
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
    """Sync fixed costs to Supabase. Handles empty dataframes."""
    try:
        supabase.table("fixed_costs").delete().eq("user_id", user_id).execute()
        if df is not None and not df.empty:
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "category": row.get("Category", "Unknown"),
                    "amount": float(row.get("Amount", 0.0)),
                    "frequency": row.get("Frequency", "Monthly")
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

def add_expense(user_id, date, desc, amount, category):
    payload = {
        "user_id": user_id,
        "date": date.isoformat(),
        "description": desc,
        "amount": float(amount),
        "category": category
    }
    supabase.table("expenses").insert(payload).execute()
