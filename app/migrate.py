import pandas as pd
import json
import os
from supabase import create_client

def resolve_data_path(*parts):
    """Resolve paths from project root with legacy fallback."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    primary = os.path.join(project_root, *parts)
    if os.path.exists(primary):
        return primary
    return os.path.join(project_root, "data", parts[-1])

def migrate():
    print("🚀 WealthOS Migration Tool")
    url = input("Supabase URL: ").strip()
    key = input("Supabase Service Role Key: ").strip()
    email = input("User Email: ").strip()
    password = input("User Password: ").strip()

    supabase = create_client(url, key)

    try:
        # 1. Login to get user_id
        auth = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user_id = auth.user.id
        print(f"✅ Authenticated: {user_id}")

        # 2. Settings Migration
        settings_path = resolve_data_path("data", "settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, 'r') as f:
                s = json.load(f)
                payload = {
                    "user_id": user_id,
                    "salary": float(s.get('salary', 0)),
                    "api_key": s.get('api_key', ''),
                    "selected_model": s.get('selected_model', 'gemini-3.8-flash')
                }
                supabase.table("user_settings").upsert(payload, on_conflict="user_id").execute()
                print("✅ Settings migrated")

        # 3. Accounts Migration
        accounts_path = resolve_data_path("data", "accounts.csv")
        if os.path.exists(accounts_path):
            df = pd.read_csv(accounts_path)
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "name": row["Account Name"],
                    "balance": float(row["Balance"]),
                    "currency": row["Currency"],
                    "type": row["Type"]
                })
            if payload:
                supabase.table("accounts").insert(payload).execute()
                print(f"✅ {len(payload)} Accounts migrated")

        # 4. Fixed Costs Migration
        fixed_costs_path = resolve_data_path("data", "fixed_costs.csv")
        if os.path.exists(fixed_costs_path):
            df = pd.read_csv(fixed_costs_path)
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "category": row["Category"],
                    "amount": float(row["Amount"]),
                    "frequency": row["Frequency"]
                })
            if payload:
                supabase.table("fixed_costs").insert(payload).execute()
                print(f"✅ {len(payload)} Fixed Costs migrated")

        # 5. Obligations Migration
        obligations_path = resolve_data_path("data", "obligations.csv")
        if os.path.exists(obligations_path):
            df = pd.read_csv(obligations_path)
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "name": row["Name"],
                    "monthly_emi": float(row["Amount"]),
                    "type": row["Type"],
                    "current_balance": float(row["Current Balance"]),
                    "currency": row["Currency"],
                    "interest_rate": float(row["Interest Rate (%)"])
                })
            if payload:
                supabase.table("obligations").insert(payload).execute()
                print(f"✅ {len(payload)} Obligations migrated")

        # 6. Investments Migration
        investments_path = resolve_data_path("data_samples", "investments.csv")
        if os.path.exists(investments_path):
            df = pd.read_csv(investments_path)
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
                print(f"✅ {len(payload)} Investments migrated")

        # 7. Expenses Migration
        expenses_path = resolve_data_path("data_samples", "expenses.csv")
        if os.path.exists(expenses_path):
            df = pd.read_csv(expenses_path)
            payload = []
            for _, row in df.iterrows():
                payload.append({
                    "user_id": user_id,
                    "date": pd.to_datetime(row["Date"]).isoformat(),
                    "description": row["Description"],
                    "amount": float(row["Amount"]),
                    "category": row["Category"]
                })
            # Batch upload expenses (Supabase handles batching)
            if payload:
                for i in range(0, len(payload), 500):
                    supabase.table("expenses").insert(payload[i:i+500]).execute()
                print(f"✅ {len(payload)} Expenses migrated")

        print("\n🎉 Migration Complete!")

    except Exception as e:
        print(f"❌ Migration Failed: {e}")

if __name__ == "__main__":
    migrate()
