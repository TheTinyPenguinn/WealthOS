"""
WealthOS v4: Personal Finance Dashboard
Tabbed layout with Investment Tracking, True Net Worth calculation, Zerodha Integration,
and Asset/Liability tracking.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import shutil
import certifi

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

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

CSV_FILE = "expenses.csv"
INVESTMENTS_FILE = "investments.csv"
BACKUP_DIR = "backups"
CATEGORIES = ["Needs", "Wants", "Financial", "Income"]
ASSET_TYPES = ["Stock", "Mutual Fund", "Gold", "ETF", "Crypto"]
HEADER_KEYWORDS = ["date", "txn date", "description", "narration", "credit", "debit", 
                   "withdrawal", "deposit", "amount", "particulars", "remarks"]

# Auto-Categorization Rules
KEYWORD_RULES = {
    "Wants": ["zomato", "swiggy", "uber", "rapido", "ola", "netflix", "amazon", 
              "pvr", "inox", "cinema", "starbucks", "kfc", "mcdonalds"],
    "Needs": ["rent", "electricity", "water", "gas", "milk", "grocery", "pharmacy", 
              "medical", "hospital", "jio", "airtel", "vi ", "act fiber"],
    "Financial": ["zerodha", "groww", "kite", "sip", "mutual fund", "premium", 
                  "insurance", "loan", "emi"]
}

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="WealthOS v4",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# DATA ENGINE - FILE I/O WITH SAFETY
# ============================================================================

def create_backup(file_path):
    """Create timestamped backup before overwriting."""
    try:
        if os.path.exists(file_path):
            if not os.path.exists(BACKUP_DIR):
                os.makedirs(BACKUP_DIR)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.basename(file_path).replace('.csv', '')
            backup_path = os.path.join(BACKUP_DIR, f"{filename}_backup_{timestamp}.csv")
            shutil.copy2(file_path, backup_path)
            return backup_path
    except Exception as e:
        st.warning(f"Backup failed: {e}")
    return None

def initialize_expenses_csv():
    """Initialize expenses.csv if missing."""
    if not os.path.exists(CSV_FILE):
        try:
            empty_df = pd.DataFrame(columns=['Date', 'Description', 'Amount', 'Category'])
            empty_df.to_csv(CSV_FILE, index=False)
        except Exception as e:
            st.error(f"Error initializing expenses CSV: {e}")

def initialize_investments_csv():
    """Initialize investments.csv if missing."""
    if not os.path.exists(INVESTMENTS_FILE):
        try:
            empty_df = pd.DataFrame(columns=['Ticker', 'Type', 'Quantity', 'Avg_Buy_Price'])
            empty_df.to_csv(INVESTMENTS_FILE, index=False)
        except Exception as e:
            st.error(f"Error initializing investments CSV: {e}")

def load_expenses():
    """Load expenses from CSV with error handling."""
    try:
        initialize_expenses_csv()
        if os.path.exists(CSV_FILE):
            df = pd.read_csv(CSV_FILE)
            if 'Date' in df.columns and not df.empty:
                df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
            for col in ['Date', 'Description', 'Amount', 'Category']:
                if col not in df.columns:
                    df[col] = None if col != 'Amount' else 0.0
            return df
        return pd.DataFrame(columns=['Date', 'Description', 'Amount', 'Category'])
    except Exception as e:
        st.error(f"Error loading expenses: {e}")
        return pd.DataFrame(columns=['Date', 'Description', 'Amount', 'Category'])

def save_expenses(df):
    """Save expenses to CSV with backup."""
    try:
        create_backup(CSV_FILE)
        df_save = df.copy()
        if 'Date' in df_save.columns and not df_save.empty:
            df_save['Date'] = pd.to_datetime(df_save['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
        df_save.to_csv(CSV_FILE, index=False)
        return True
    except Exception as e:
        st.error(f"Error saving expenses: {e}")
        return False

def load_investments():
    """Load investments from CSV with error handling."""
    try:
        initialize_investments_csv()
        if os.path.exists(INVESTMENTS_FILE):
            df = pd.read_csv(INVESTMENTS_FILE)
            for col in ['Ticker', 'Type', 'Quantity', 'Avg_Buy_Price']:
                if col not in df.columns:
                    df[col] = '' if col in ['Ticker', 'Type'] else 0.0
            return df
        return pd.DataFrame(columns=['Ticker', 'Type', 'Quantity', 'Avg_Buy_Price'])
    except Exception as e:
        st.error(f"Error loading investments: {e}")
        return pd.DataFrame(columns=['Ticker', 'Type', 'Quantity', 'Avg_Buy_Price'])

def save_investments(df):
    """Save investments to CSV with backup."""
    try:
        create_backup(INVESTMENTS_FILE)
        df.to_csv(INVESTMENTS_FILE, index=False)
        return True
    except Exception as e:
        st.error(f"Error saving investments: {e}")
        return False

# ============================================================================
# INVESTMENT ENGINE - PRICE FETCHING WITH CACHING
# ============================================================================

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
        
        # Skip yfinance for Mutual Funds (they don't have Yahoo tickers)
        if asset_type != 'Mutual Fund':
            live_price = fetch_live_price(ticker)
            # Small delay to avoid rate limiting (only if not cached)
            if idx > 0:
                time.sleep(0.1)
        
        if live_price is None:
            if asset_type != 'Mutual Fund':  # Only track failures for non-MF
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

def clean_numeric(value):
    """Clean Indian number format (e.g., 1,20,000.00) to float."""
    if pd.isna(value):
        return 0.0
    try:
        cleaned = str(value).replace(',', '').replace(' ', '').strip()
        if cleaned == '' or cleaned == '-':
            return 0.0
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0

def parse_bank_csv(uploaded_file):
    """Parse messy Indian bank CSV with smart header detection & Sweep Filtering."""
    try:
        content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
        lines = content.splitlines()
        
        header_idx = -1
        for i, line in enumerate(lines[:40]):
            line_lower = line.lower()
            if "transaction date" in line_lower and "amount" in line_lower:
                header_idx = i
                break
        
        if header_idx == -1:
            st.error("Could not find a valid header row containing 'Transaction Date' and 'Amount'.")
            return None

        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, header=header_idx, dtype=str, on_bad_lines='skip')
        
        col_map = {}
        amount_col = None
        type_col = None 
        
        for col in df.columns:
            c_lower = col.lower().strip()
            if 'date' in c_lower and 'value' not in c_lower:
                col_map[col] = 'Date'
            elif 'description' in c_lower or 'narration' in c_lower:
                col_map[col] = 'Description'
            elif c_lower == 'amount':
                amount_col = col
                col_map[col] = 'Amount'
            elif 'dr' in c_lower and 'cr' in c_lower and 'balance' not in c_lower:
                if type_col is None: 
                    type_col = col

        df = df.rename(columns=col_map)
        
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['Date']) 
            
        if 'Amount' in df.columns:
            df['Amount'] = df['Amount'].apply(clean_numeric)
            
            if type_col and type_col in df.columns:
                def apply_sign(row):
                    amt = row['Amount']
                    txn_type = str(row[type_col]).upper().strip()
                    if 'DR' in txn_type:
                        return -abs(amt)
                    elif 'CR' in txn_type:
                        return abs(amt)
                    return amt
                df['Amount'] = df.apply(apply_sign, axis=1)

        if 'Description' in df.columns:
            df['Description'] = df['Description'].fillna('Unknown')
            ignore_keywords = ['sweep', 'fd premat', 'fd maturity', 'auto trf']
            pattern = '|'.join(ignore_keywords)
            df = df[~df['Description'].str.contains(pattern, case=False, na=False)]

        df['Category'] = 'Needs'
        
        return df[['Date', 'Description', 'Amount', 'Category']]
        
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
# AUTO-CATEGORIZATION ENGINE (with UPI logic)
# ============================================================================

def auto_categorize(df, force_overwrite=False):
    """Auto-categorize transactions with UPI logic."""
    changes = 0
    df = df.copy()
    
    for idx, row in df.iterrows():
        current_cat = str(row.get('Category', 'Needs')).strip()
        desc = str(row.get('Description', ''))
        desc_lower = desc.lower()
        amount = float(row.get('Amount', 0))
        
        if current_cat != 'Needs' and not force_overwrite:
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
                # Rule 3: Keyword matching
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
# METRICS CALCULATION
# ============================================================================

def calculate_metrics(expenses_df, investments_df, bank_balance):
    """Calculate dashboard metrics including True Net Worth."""
    monthly_spend = 0.0
    savings_rate = 0.0
    total_income = 0.0
    total_spend = 0.0
    
    if not expenses_df.empty and 'Amount' in expenses_df.columns:
        try:
            total_income = expenses_df[expenses_df['Amount'] > 0]['Amount'].sum()
            total_spend = abs(expenses_df[expenses_df['Amount'] < 0]['Amount'].sum())
            
            current_month = datetime.now().strftime('%Y-%m')
            df_copy = expenses_df.copy()
            df_copy['Month'] = pd.to_datetime(df_copy['Date'], errors='coerce').dt.to_period('M').astype(str)
            monthly_df = df_copy[df_copy['Month'] == current_month]
            monthly_spend = abs(monthly_df[monthly_df['Amount'] < 0]['Amount'].sum())
            
            if total_income > 0:
                savings_rate = ((total_income - total_spend) / total_income) * 100
        except Exception:
            pass
    
    # Portfolio value
    portfolio_value = 0.0
    if not investments_df.empty:
        portfolio = get_portfolio_with_prices(investments_df)
        if not portfolio.empty and 'Current_Value' in portfolio.columns:
            portfolio_value = portfolio['Current_Value'].sum()
    
    # True Net Worth = Bank Balance + Portfolio Value
    net_worth = bank_balance + portfolio_value
    
    return net_worth, monthly_spend, savings_rate, portfolio_value

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if 'expenses' not in st.session_state:
    st.session_state.expenses = load_expenses()

if 'investments' not in st.session_state:
    st.session_state.investments = load_investments()

if 'parsed_csv' not in st.session_state:
    st.session_state.parsed_csv = None

if 'bank_balance' not in st.session_state:
    st.session_state.bank_balance = 0.0

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.title("💰 WealthOS v4")
    
    st.divider()
    
    # --- MULTI-ACCOUNT TRACKING (Assets vs Liabilities) ---
    st.header("🏦 Accounts & Cash")
    
    if 'accounts' not in st.session_state:
        st.session_state.accounts = pd.DataFrame({
            'Account Name': ['Main Savings', 'Salary Acct', 'Credit Card', 'Cash'],
            'Balance': [0.0, 0.0, 0.0, 0.0],
            'Type': ['Asset', 'Asset', 'Liability', 'Asset']
        })

    # Editable Table with Asset/Liability type
    edited_accounts = st.data_editor(
        st.session_state.accounts,
        column_config={
            "Account Name": st.column_config.TextColumn("Name"),
            "Balance": st.column_config.NumberColumn("Balance (₹)", format="₹%.2f"),
            "Type": st.column_config.SelectboxColumn("Type", options=['Asset', 'Liability'], required=True)
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="accounts_editor"
    )
    st.session_state.accounts = edited_accounts
    
    # Calculate Assets, Liabilities, and Net Liquid Cash
    total_assets = edited_accounts[edited_accounts['Type'] == 'Asset']['Balance'].sum()
    total_debt = edited_accounts[edited_accounts['Type'] == 'Liability']['Balance'].sum()
    net_liquid_cash = total_assets - total_debt
    
    st.session_state.bank_balance = net_liquid_cash
    
    # Display summary
    st.caption(f"**Total Assets:** ₹{total_assets:,.2f}")
    st.caption(f"**Total Debt:** ₹{total_debt:,.2f}")
    st.caption(f"**Net Liquid Cash:** ₹{net_liquid_cash:,.2f}")
    
    st.divider()
    
    # Add Transaction Form
    st.header("➕ Add Transaction")
    with st.form("add_transaction_form", clear_on_submit=True):
        txn_date = st.date_input("Date", value=date.today())
        txn_desc = st.text_input("Description")
        txn_amount = st.number_input("Amount (₹)", step=100.0, format="%.2f", help="Negative for expense")
        txn_category = st.selectbox("Category", options=CATEGORIES)
        
        if st.form_submit_button("Add Transaction", use_container_width=True):
            if txn_desc:
                new_row = pd.DataFrame([{
                    'Date': pd.Timestamp(txn_date),
                    'Description': txn_desc,
                    'Amount': txn_amount,
                    'Category': txn_category
                }])
                st.session_state.expenses = pd.concat(
                    [st.session_state.expenses, new_row],
                    ignore_index=True
                )
                if save_expenses(st.session_state.expenses):
                    st.success("Transaction added!")
                    st.rerun()
    
    st.divider()
    
    # Add Asset Form
    st.header("📈 Add Asset")
    with st.form("add_asset_form", clear_on_submit=True):
        asset_type = st.selectbox("Type", options=ASSET_TYPES)
        asset_ticker = st.text_input("Ticker", placeholder="e.g., RELIANCE.NS")
        asset_qty = st.number_input("Quantity", min_value=0.0, step=1.0, format="%.2f")
        asset_avg_price = st.number_input("Avg Buy Price (₹)", min_value=0.0, step=10.0, format="%.2f")
        
        if st.form_submit_button("Add Asset", use_container_width=True):
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
                if save_investments(st.session_state.investments):
                    st.success("Asset added!")
                    fetch_live_price.clear()  # Clear cache to fetch new price
                    st.rerun()
    
    st.divider()
    
    # CSV Uploader
    st.header("📤 Import CSV")
    uploaded_file = st.file_uploader(
        "Upload Bank Statement",
        type=['csv'],
        help="Supports Indian bank CSVs"
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

# ============================================================================
# MAIN PAGE - TABBED LAYOUT
# ============================================================================

st.title("WealthOS v4")

tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "💸 Transactions", "📈 Investments"])

# ============================================================================
# TAB 1: DASHBOARD
# ============================================================================

with tab1:
    net_worth, monthly_spend, savings_rate, portfolio_value = calculate_metrics(
        st.session_state.expenses,
        st.session_state.investments,
        st.session_state.bank_balance
    )
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("True Net Worth", f"₹{net_worth:,.2f}")
    
    with col2:
        st.metric("Bank Balance", f"₹{st.session_state.bank_balance:,.2f}")
    
    with col3:
        st.metric("Portfolio Value", f"₹{portfolio_value:,.2f}")
    
    with col4:
        st.metric("Monthly Spend", f"₹{monthly_spend:,.2f}")
    
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Savings Rate")
        st.metric("", f"{savings_rate:.1f}%")
    
    with col2:
        st.subheader("Spending by Category")
        if not st.session_state.expenses.empty:
            spend_df = st.session_state.expenses[st.session_state.expenses['Amount'] < 0].copy()
            if not spend_df.empty:
                spend_df['Amount'] = spend_df['Amount'].abs()
                cat_spend = spend_df.groupby('Category')['Amount'].sum().reset_index()
                st.dataframe(cat_spend, use_container_width=True, hide_index=True)
            else:
                st.info("No spending data")
        else:
            st.info("No transactions yet")

# ============================================================================
# TAB 2: TRANSACTIONS
# ============================================================================

with tab2:
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
                    st.session_state.expenses = pd.concat(
                        [st.session_state.expenses, unique_new],
                        ignore_index=True
                    )
                    if save_expenses(st.session_state.expenses):
                        st.success(f"Added {len(unique_new)} transactions")
                        st.session_state.parsed_csv = None
                        st.rerun()
        with col2:
            if st.button("Clear Preview", use_container_width=True):
                st.session_state.parsed_csv = None
                st.rerun()
        
        st.divider()
    
    # Auto-Categorize Section
    st.subheader("⚡ Auto-Categorize")
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
                    st.session_state.expenses = updated_df
                    if save_expenses(updated_df):
                        st.toast(f"✅ Categorized {changes} transactions!")
                        st.rerun()
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
            key="transaction_editor"
        )
        
        if st.button("Save Changes", type="primary", key="save_transactions"):
            if 'Date' in edited_df.columns:
                edited_df['Date'] = pd.to_datetime(edited_df['Date'], errors='coerce')
            st.session_state.expenses = edited_df
            if save_expenses(st.session_state.expenses):
                st.success("Changes saved!")
                st.rerun()
    else:
        st.info("No transactions yet. Import a bank statement using the sidebar.")

# ============================================================================
# TAB 3: INVESTMENTS
# ============================================================================

with tab3:
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
                    save_investments(st.session_state.investments)
                    st.success("Portfolio merged successfully!")
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
                    save_investments(st.session_state.investments)
                    st.success("Stocks replaced! Crypto/Gold preserved.")
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
            
            styled_df = display_portfolio.style.applymap(
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
                if save_investments(st.session_state.investments):
                    st.success("Holdings saved!")
                    fetch_live_price.clear()
                    st.rerun()
    else:
        st.info("No investments yet. Add assets using the sidebar.")

# ============================================================================
# FOOTER
# ============================================================================

st.divider()
st.caption("WealthOS v4 • Built with Streamlit")