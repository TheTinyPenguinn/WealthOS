"""
WealthOS v4: Personal Finance Dashboard
Tabbed layout with Investment Tracking, True Net Worth calculation, Zerodha Integration,
and Asset/Liability tracking.
"""

import streamlit as st
import pandas as pd
import numpy as np
import os
import shutil
import json
from datetime import date, datetime
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

# Optional Google Gemini import for AI features (new google.genai package)
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None

# ============================================================================
# GLOBAL HELPER: LIVE CURRENCY
# ============================================================================

@st.cache_data(ttl=3600)  # 1 hour cache
def get_usd_rate():
    """Get live USD to INR exchange rate with fallback."""
    try:
        if YFINANCE_AVAILABLE:
            ticker = yf.Ticker("USDINR=X")
            rate = ticker.history(period="1d")['Close'].iloc[-1]
            return float(rate)
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
# PERSISTENCE ENGINE
# ============================================================================

def save_all_data_callback():
    """Force immediate save of all data to disk."""
    try:
        save_data(st.session_state.accounts, st.session_state.fixed_costs, st.session_state.obligations)
    except Exception as e:
        st.error(f"Error saving data: {e}")

def load_data():
    """Load configuration data from CSV files or return defaults."""
    try:
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Load accounts
        if os.path.exists('data/accounts.csv'):
            accounts_df = pd.read_csv('data/accounts.csv')
            # Ensure Currency column exists
            if 'Currency' not in accounts_df.columns:
                accounts_df['Currency'] = 'INR'
        else:
            accounts_df = pd.DataFrame({
                'Account Name': ['Main Savings', 'Salary Acct', 'Credit Card', 'Cash'],
                'Balance': [0.0, 0.0, 0.0, 0.0],
                'Currency': ['INR', 'INR', 'INR', 'INR'],
                'Type': ['Bank/Cash', 'Bank/Cash', 'Credit Card', 'Bank/Cash']
            })

        # Load fixed costs
        if os.path.exists('data/fixed_costs.csv'):
            fixed_df = pd.read_csv('data/fixed_costs.csv')
        else:
            fixed_df = pd.DataFrame({
                'Category': ['Rent', 'Groceries', 'Utilities', 'Transport', 'Entertainment', 'Insurance'],
                'Amount': [25000, 5000, 1500, 2000, 12000, 2000],
                'Frequency': ['Monthly', 'Monthly', 'Monthly', 'Monthly', 'Yearly', 'Monthly']
            })

        # Load obligations
        if os.path.exists('data/obligations.csv'):
            obligations_df = pd.read_csv('data/obligations.csv')
            # Ensure required columns exist
            required_cols = ['Current Balance', 'Currency', 'Interest Rate (%)']
            for col in required_cols:
                if col not in obligations_df.columns:
                    obligations_df[col] = 0.0 if col in ['Current Balance', 'Interest Rate (%)'] else 'INR'
        else:
            obligations_df = pd.DataFrame({
                'Name': ['Student Loan', 'ELSS SIP', 'Professional Tax'],
                'Amount': [11000, 5000, 200],
                'Type': ['Loan', 'SIP', 'Tax'],
                'Current Balance': [0.0, 0.0, 0.0],
                'Currency': ['INR', 'INR', 'INR'],
                'Interest Rate (%)': [10.0, 0.0, 0.0]
            })

        return accounts_df, fixed_df, obligations_df
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
        # Return defaults if loading fails
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def save_data(accounts_df, fixed_df, obligations_df):
    """Save configuration data to CSV files."""
    try:
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        accounts_df.to_csv('data/accounts.csv', index=False)
        fixed_df.to_csv('data/fixed_costs.csv', index=False)
        obligations_df.to_csv('data/obligations.csv', index=False)
    except Exception as e:
        st.error(f"Error saving configuration: {e}")

def load_settings():
    """Load user settings from JSON file."""
    try:
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        if os.path.exists('data/settings.json'):
            with open('data/settings.json', 'r') as f:
                return json.load(f)
    except Exception:
        pass
    # Return defaults
    return {
        'salary': 50000.0,
        'api_key': '',
        'selected_model': 'gemini-1.5-flash'
    }

def save_settings(salary, api_key, selected_model):
    """Save user settings to JSON file.
    
    SECURITY NOTE: API key is stored in plain text. This is convenient but not secure
    if you share your laptop. Consider using environment variables or a secure vault
    for production deployments.
    """
    try:
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        settings = {
            'salary': salary,
            'api_key': api_key,
            'selected_model': selected_model
        }
        with open('data/settings.json', 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        st.error(f"Error saving settings: {e}")

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

# WinRAR Trust Model
if 'usage_count' not in st.session_state:
    st.session_state.usage_count = 0
st.session_state.usage_count += 1
if st.session_state.usage_count > 3:
    st.toast(" WealthOS is free. If it helps you survive, consider buying a license.", icon="💰")

st.set_page_config(
    page_title="WealthOS v4",
    page_icon="",
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
                # Future Date Warning
                if df['Date'].max() > pd.Timestamp.now() + pd.Timedelta(days=30):
                    st.toast("⚠️ Future dates detected. Check DD/MM format.")
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

def generate_financial_context(net_worth, liquid_cash, total_debt, true_burn, surplus, fixed_living, total_emi, csv_variable_spend, avg_interest):
    """Generates a summary string of the user's financial health for the AI using passed arguments."""
    try:
        salary = st.session_state.get('salary', 0.0)
        
        summary = f"""
        💰 CASH FLOW POWER (MONTHLY):
        - Income: ₹{salary:,.2f}
        - Effective Burn: ₹{true_burn:,.2f} (Fixed: ₹{fixed_living:,.2f} + EMI: ₹{total_emi:,.2f} + Variable: ₹{csv_variable_spend:,.2f})
        - 🚀 INVESTIBLE SURPLUS: ₹{surplus:,.2f} / month ({(surplus/salary*100) if salary > 0 else 0:.1f}%)

        🏦 BALANCE SHEET & DEBT:
        - Liquid Cash: ₹{liquid_cash:,.2f}
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

def plot_runway_impact(liquid_cash, monthly_burn, upi_bleed):
    """Create runway impact visualization with gain calculation."""
    try:
        if monthly_burn <= 0:
            return None
            
        current_runway = liquid_cash / monthly_burn
        potential_runway = liquid_cash / max(1, (monthly_burn - upi_bleed))
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
    salary = st.session_state.get('salary', 0.0)
    fx_rate = get_usd_rate()
    
    # 1. FIXED COSTS (Monthly Floor)
    monthly_floor = 0.0
    if 'fixed_costs' in st.session_state:
        for _, row in st.session_state.fixed_costs.iterrows():
            amt = float(row['Amount'])
            freq = row['Frequency']
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
            if row['Type'] == 'Loan':
                total_emi += float(row['Amount'])
                principal = float(row['Current Balance'])
                if row['Currency'] == 'USD': principal *= fx_rate
                
                total_debt_balance += principal
                rate = float(row['Interest Rate (%)'])
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
        val = float(row['Balance'])
        if row.get('Currency') == 'USD': val *= fx_rate
        
        t = row['Type']
        account_name = str(row.get('Account Name', '')).lower()
        
        # Strict Loan Segregation: Skip any loan/debt entries
        if t == 'Loan' or 'loan' in account_name or 'debt' in account_name:
            st.warning(f"⚠️ '{row.get('Account Name', 'Unknown')}' ignored. Please move loans to 'Financial Obligations'.")
            continue
        
        if t == 'Bank/Cash': bank_cash += val
        elif t == 'Credit Card': credit_card += val
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

    # Final Totals (Fixed: Use only total_debt_balance from Obligations)
    total_portfolio = csv_portfolio_value + investments_sidebar
    net_liquidity = bank_cash - credit_card 
    # FIXED: Use total_debt_balance as definitive debt source (no double counting)
    total_debt_all = total_debt_balance
    net_worth = (net_liquidity + total_portfolio) - total_debt_balance

    return net_worth, net_liquidity, total_debt_all, total_portfolio, true_burn, surplus_margin, surplus, monthly_interest_burn, avg_interest, rsu_real_value, monthly_floor, total_emi, csv_variable_spend, unexpected_needs


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if 'expenses' not in st.session_state:
    st.session_state.expenses = load_expenses()

if 'investments' not in st.session_state:
    st.session_state.investments = load_investments()

if 'parsed_csv' not in st.session_state:
    st.session_state.parsed_csv = pd.DataFrame(columns=['Date', 'Description', 'Amount', 'Category'])

# Load persisted configuration data
if 'accounts' not in st.session_state:
    st.session_state.accounts, st.session_state.fixed_costs, st.session_state.obligations = load_data()

# Load persisted user settings
if 'salary' not in st.session_state:
    settings = load_settings()
    st.session_state.salary = settings.get('salary', 50000.0)
    st.session_state.api_key = settings.get('api_key', '')
    st.session_state.selected_model = settings.get('selected_model', 'gemini-1.5-flash')

# ============================================================================
# SIDEBAR - RICH CLASSIC DESIGN
# ============================================================================

st.sidebar.title("💰 WealthOS v5")

# --- SETTINGS (TOP) ---
st.sidebar.markdown("### ⚙️ Settings")

salary_input = st.sidebar.number_input("Monthly Salary (₹)", value=st.session_state.salary, step=5000.0)
if salary_input != st.session_state.salary:
    st.session_state.salary = salary_input
    save_settings(salary_input, st.session_state.api_key, st.session_state.selected_model)

api_key = st.sidebar.text_input("Gemini API Key", type="password", value=st.session_state.get('api_key', ''), help="Get key from Google AI Studio")
if api_key != st.session_state.get('api_key', ''):
    st.session_state.api_key = api_key
    save_settings(st.session_state.salary, api_key, st.session_state.selected_model)

st.sidebar.divider()

# --- ACCOUNTS & CASH ---
with st.sidebar.expander("🏦 Accounts & Cash", expanded=True):
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
        key="accounts_editor",
        on_change=save_all_data_callback
    )
    st.session_state.accounts = edited_accounts
    
    # Calculate distinct accounting buckets with currency conversion (Fixed: No Loan counting)
    fx_rate = get_usd_rate()
    bank_cash = 0.0
    credit_card = 0.0
    investments_sidebar = 0.0
    
    for _, row in edited_accounts.iterrows():
        val = row['Balance']
        if row['Currency'] == 'USD':
            val = val * fx_rate
        
        if row['Type'] == 'Bank/Cash':
            bank_cash += val
        elif row['Type'] == 'Credit Card':
            credit_card += val
        elif row['Type'] == 'Investment (Non-Zerodha)':
            investments_sidebar += val
        # NOTE: Loans are now handled only in Financial Obligations section
    
    # Liquid Cash (Runway Fuel) = Bank/Cash - Credit Card
    liquid_cash = bank_cash - credit_card
    
    # Total Debt from Accounts = Credit Card only (Loans handled in Obligations)
    total_debt = credit_card
    
    st.session_state.bank_balance = liquid_cash
    
    # Display summary
    st.caption(f"**Net Liquidity:** ₹{liquid_cash:,.2f}")
    st.caption(f"**Total Debt:** ₹{total_debt:,.2f}")
    st.caption(f"**Investments:** ₹{investments_sidebar:,.2f}")

st.sidebar.divider()

# --- MONTHLY COMMITMENTS ---
with st.sidebar.expander("🔒 Monthly Commitments", expanded=True):
    # Fixed Living Costs
    with st.expander("🏠 Fixed Living Costs", expanded=True):
        fixed_costs = st.data_editor(
            st.session_state.fixed_costs,
            column_config={
                "Category": st.column_config.TextColumn("Category"),
                "Amount": st.column_config.NumberColumn("Amount (₹)", format="₹%.2f"),
                "Frequency": st.column_config.SelectboxColumn("Frequency", options=['Monthly', 'Quarterly', 'Half-Yearly', 'Yearly'])
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            key="fixed_costs_editor",
            on_change=save_all_data_callback
        )
        st.session_state.fixed_costs = fixed_costs
    
    # Financial Obligations
    with st.expander("💳 Financial Obligations (Debt/SIP)", expanded=True):
        # Schema Migration: Add new columns if missing
        required_cols = ['Current Balance', 'Currency', 'Interest Rate (%)']
        for col in required_cols:
            if col not in st.session_state.obligations.columns:
                st.session_state.obligations[col] = 0.0 if col in ['Current Balance', 'Interest Rate (%)'] else 'INR'
        
        # Fill NaN values with defaults
        st.session_state.obligations['Current Balance'].fillna(0.0, inplace=True)
        st.session_state.obligations['Currency'].fillna('INR', inplace=True)
        st.session_state.obligations['Interest Rate (%)'].fillna(10.0, inplace=True)
        
        obligations = st.data_editor(
            st.session_state.obligations,
            column_config={
                "Name": st.column_config.TextColumn("Name"),
                "Amount": st.column_config.NumberColumn("Monthly EMI (₹)", format="₹%.2f"),
                "Type": st.column_config.SelectboxColumn("Type", options=['Loan', 'SIP']),
                "Current Balance": st.column_config.NumberColumn("Current Balance", format="₹%.2f", help="Remaining amount you owe"),
                "Currency": st.column_config.SelectboxColumn("Currency", options=['INR', 'USD']),
                "Interest Rate (%)": st.column_config.NumberColumn("Interest Rate (%)", format="%.1f%%")
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            key="obligations_editor",
            on_change=save_all_data_callback
        )
        st.session_state.obligations = obligations
        
        # Real-Time Debt Trap Detection
        for _, row in obligations.iterrows():
            if row['Type'] == 'Loan':
                principal = row['Current Balance']
                if row['Currency'] == 'USD':
                    principal *= 85.0  # Convert to INR
                
                monthly_interest = (principal * (row['Interest Rate (%)'] / 100)) / 12
                emi = row['Amount']
                
                if emi < monthly_interest:
                    st.error(f"⚠️ Debt Trap Alert: {row['Name']} - EMI (₹{emi:,.0f}) < Monthly Interest (₹{monthly_interest:,.0f})")

st.sidebar.divider()

# --- ACTIONS ---
st.sidebar.markdown("### 📥 Data Import")

# Add Transaction Form
st.sidebar.markdown("#### ➕ Add Transaction")
with st.sidebar.form("add_txn_form", clear_on_submit=True):
    txn_date = st.date_input("Date", value=datetime.now().date())
    txn_desc = st.text_input("Description", placeholder="Coffee at Starbucks")
    txn_amount = st.number_input("Amount", step=100.0, format="%.2f")
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

st.sidebar.divider()

# Add Asset Form
st.sidebar.markdown("#### 📈 Add Asset")
with st.sidebar.form("add_asset_form", clear_on_submit=True):
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

st.sidebar.divider()

# CSV Uploader
st.sidebar.markdown("#### 📤 Import CSV")
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

st.sidebar.caption("💾 All data is automatically saved locally")

# ============================================================================
# MAIN PAGE - TABBED LAYOUT
# ============================================================================

st.title("WealthOS v4")

tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "💸 Transactions", "📈 Investments", "🤖 AI Brain"])

# ============================================================================
# TAB 1: DASHBOARD (Upgraded with Visuals)
# ============================================================================

with tab1:
    # Calculate Cash Flow First metrics for high-income users
    salary = st.session_state.get('salary', 0.0)
    net_worth, liquid_cash, total_debt, total_portfolio, true_burn, surplus_margin, surplus, monthly_interest_burn, avg_interest, rsu_real_value, monthly_floor, total_emi, csv_variable_spend, unexpected_needs = calculate_metrics(
        st.session_state.expenses,
        st.session_state.investments,
        st.session_state.accounts
    )
    
    # Legacy compatibility for existing code
    monthly_spend = true_burn
    savings_rate = surplus_margin
    fixed_living = monthly_floor  # Now properly calculated
    
    # --- METRICS ROW ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("True Net Worth", f"₹{net_worth:,.0f}", delta="Total Wealth")
    with col2:
        surplus_color = "normal" if surplus > 0 else "inverse"
        st.metric("Net Liquidity", f"₹{liquid_cash:,.0f}", delta_color=surplus_color, help="Available cash after credit card debt")
    with col3:
        st.metric("Debt Interest Burn", f"₹{monthly_interest_burn:,.0f}", delta_color="inverse", help="Money lost to interest every month")
    with col4:
        freedom_rate = surplus / 160 if (surplus > 0 and salary > 0) else 0
        st.metric("Freedom Rate", f"₹{freedom_rate:,.0f}/hr", help="Real Hourly Savings Rate")
    
    # Fixed vs Variable Progress Bar
    if true_burn > 0:
        fixed_pct = (fixed_living + total_emi) / true_burn * 100
        st.progress(fixed_pct/100, text=f"{fixed_pct:.0f}% of your burn is Fixed")
    
    # Debug UI: Burn Breakdown
    st.caption(f"🔍 Burn Breakdown: Fixed ₹{monthly_floor:,.0f} + EMI ₹{total_emi:,.0f} + Variable ₹{csv_variable_spend:,.0f} + Unexpected ₹{unexpected_needs:,.0f}")
    
    st.divider()
    
    st.divider()
    
    st.subheader("💀 Survival Stats")
    upi_bleed, real_hourly, zero_days = analyze_survival_metrics(st.session_state.expenses, st.session_state.salary)

    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric("UPI Bleed (Micro-cuts)", f"₹{upi_bleed:,.0f}", help="Total UPI spends < ₹500")
    with s2:
        st.metric("Real Hourly Wage", f"₹{real_hourly:,.0f}/hr", help="(Salary - Needs) / 160 hrs")
    with s3:
        st.metric("Zero Spend Days", f"{zero_days}", help="Days in last 30 days with ₹0 spend")
    
    st.divider()
    
    # --- FUTURE SIMULATION CONTAINER ---
    st.subheader("🔮 Future Simulation")
    
    # Runway Extender Chart
    runway_chart = plot_runway_impact(liquid_cash, true_burn, upi_bleed)
    if runway_chart:
        st.plotly_chart(runway_chart, use_container_width=True)
    
    # Detected Recurring Expenses
    subscriptions = analyze_subscriptions(st.session_state.expenses)
    if not subscriptions.empty:
        with st.expander("🔄 Detected Recurring Expenses"):
            display_cols = ['Count', 'Monthly_Avg', 'Yearly_Cost', 'Status']
            display_df = subscriptions[display_cols].rename(columns={
                'Count': 'Transactions',
                'Monthly_Avg': 'Monthly Avg',
                'Yearly_Cost': 'Yearly Cost'
            })
            st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    st.divider()
    
    # --- VISUALS ROW ---
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("💸 Spending Health")
        if true_burn > 0:
            # Create a "Burn Bar" - borrowing from React idea
            # Assuming a simplified "Budget" of Income (if available) or just visualization
            st.caption("Spending Mix (Needs vs Wants)")
            
            # Calculate Needs/Wants split
            mask = st.session_state.expenses['Amount'] < 0
            needs = st.session_state.expenses[mask & (st.session_state.expenses['Category'] == 'Needs')]['Amount'].sum()
            wants = st.session_state.expenses[mask & (st.session_state.expenses['Category'] == 'Wants')]['Amount'].sum()
            total = abs(needs) + abs(wants)
            
            if total > 0:
                needs_pct = (abs(needs) / total)
                wants_pct = (abs(wants) / total)
                
                st.progress(needs_pct, text=f"Needs: {int(needs_pct*100)}%")
                st.progress(wants_pct, text=f"Wants: {int(wants_pct*100)}%")
                
                if wants_pct > 0.3:
                    st.warning(f"⚠️ High 'Wants' Usage: {int(wants_pct*100)}% of tracked spending.")
                else:
                    st.success("✅ Healthy 'Wants' Ratio (<30%)")

    with c2:
        st.subheader("Surplus Analysis")
        if surplus > 0:
            st.success(f"🚀 Positive Surplus: ₹{surplus:,.0f}/month ({surplus_margin:.1f}%)")
        else:
            st.error(f"📉 Negative Surplus: ₹{surplus:,.0f}/month ({surplus_margin:.1f}%)")
        
        st.caption("💡 Use surplus for debt repayment or investments")

    st.divider()
    
    # --- DEBUG: ANOMALY INSPECTOR ---
    st.subheader("🕵️‍♀️ Anomaly Inspector")
    st.caption("These transactions are currently labeled 'Needs' or 'Wants' and are over ₹20k. They are ruining your runway math.")
    
    if not st.session_state.expenses.empty:
        # Filter exactly what the AI sees
        mask = (st.session_state.expenses['Amount'] < 0) & \
               (st.session_state.expenses['Category'].isin(['Needs', 'Wants'])) & \
               (st.session_state.expenses['Amount'].abs() > 20000)
        
        anomalies = st.session_state.expenses[mask].copy()
        
        if not anomalies.empty:
            st.dataframe(anomalies, use_container_width=True)
            st.warning(f"⚠️ Total Anomalies: ₹{anomalies['Amount'].abs().sum():,.2f}")
            st.info("👉 Go to the 'Transactions' tab and change these to 'Financial' or 'One-Time' to remove them from your Burn Rate.")
        else:
            st.success("✅ No large anomalies found in Needs/Wants!")

# ============================================================================
# TAB 2: TRANSACTIONS
# ============================================================================

with tab2:
    # Search and Filter
    search_term = st.text_input("🔍 Search Transactions", placeholder="Search by Description or Category...")
    
    # Action Buttons
    btn1, btn2, btn3 = st.columns([3, 1, 1])
    with btn1:
        pass  # Empty space for search
    with btn2:
        if st.button("🔥 Sort by Amount", use_container_width=True):
            if not st.session_state.expenses.empty:
                st.session_state.expenses = st.session_state.expenses.sort_values('Amount', ascending=True)
                if save_expenses(st.session_state.expenses):
                    st.success("Sorted by Amount")
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
# ============================================================================
# TAB 4: AI BRAIN (Fixed & Robust)
# ============================================================================

with tab4:
    st.header("🤖 WealthOS Consultant")
    st.caption("Powered by Google Gemini")
    
    # --- CONNECTION DOCTOR & SETTINGS ---
    with st.expander("🛠️ AI Settings & Status", expanded=False):
        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("Check API Access"):
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=st.session_state.api_key)
                    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    st.session_state.available_models = models
                    st.success(f"✅ Found {len(models)} models!")
                except Exception as e:
                    st.error(f"Connection Failed: {e}")
        
        with c2:
            # Model Selector
            current_model = st.session_state.get('selected_model', 'gemini-1.5-flash')
            # If we have a list from the check, use it
            opts = st.session_state.get('available_models', ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash'])
            
            new_model = st.selectbox("Select Model", options=opts, index=0 if current_model not in opts else opts.index(current_model))
            if new_model != current_model:
                st.session_state.selected_model = new_model
                save_settings(st.session_state.salary, st.session_state.api_key, new_model)

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
        if not st.session_state.api_key:
            st.error("Please enter your Gemini API Key in the Sidebar.")
        else:
            with st.spinner("Thinking..."):
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=st.session_state.api_key)
                    
                    # 1. Get Context (Fixed: Pass all required parameters)
                    financial_context = generate_financial_context(net_worth, liquid_cash, total_debt, true_burn, surplus, fixed_living, total_emi, csv_variable_spend, avg_interest)
                    
                    # 2. Prompt
                    full_prompt = f"""
                    Role: You are a Strategic CFO for a High-Income Earner.
                    
                    DATA SUMMARY:
                    {financial_context}
                    
                    USER QUESTION:
                    {user_query}
                    
                    INSTRUCTIONS:
                    - Focus on 'Surplus Deployment'.
                    - Compare Investment Returns vs Debt Interest (Avg Rate: {avg_interest:.1f}%).
                    - Be mathematical and direct.
                    - Use Markdown.
                    """
                    
                    # 3. Generate
                    model = genai.GenerativeModel(st.session_state.selected_model)
                    response = model.generate_content(full_prompt)
                    
                    st.markdown("### 🧠 CFO Analysis")
                    st.markdown(response.text)
                    
                except Exception as e:
                    if "429" in str(e):
                        st.error("⚠️ Quota Limit Hit. Please wait 30s.")
                    else:
                        st.error(f"Error: {e}")


# ============================================================================
# FOOTER
# ============================================================================

st.divider()
st.caption("WealthOS v4 • Built with Streamlit")