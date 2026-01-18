"""
WealthOS: Personal Finance Dashboard
A sophisticated financial management application with CSV persistence and Obsidian theme.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date
import os
import time

# Optional import for yfinance (with error handling)
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except (ImportError, TypeError) as e:
    YFINANCE_AVAILABLE = False
    yf = None

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

CSV_FILE = "expenses.csv"
STOCK_CACHE_DURATION = 300  # 5 minutes in seconds
LIVE_TICKERS = ["RELIANCE.NS", "TCS.NS", "GOLDBEES.NS"]

# Category mapping: Type -> Sub-Category
CATEGORY_MAP = {
    "Needs": ["Groceries", "Rent", "Medical", "Bills"],
    "Wants": ["Dining Out", "Travel", "Shopping", "Entertainment"],
    "Financial": ["SIP", "Loan EMI", "Insurance"]
}

# Plotly dark theme colors
PLOTLY_COLORS = {
    "neon_blue": "#00D9FF",
    "cyan": "#00FFFF",
    "purple": "#B026FF"
}

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="WealthOS",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# CUSTOM CSS - WEALTHOS OBSIDIAN THEME
# ============================================================================

def inject_custom_css():
    """Inject custom CSS for WealthOS Obsidian matte black theme."""
    css = """
    <style>
    /* Main app background - Matte Black */
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    
    /* Remove default padding */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 100%;
    }
    
    /* Metric cards - Clean, flat, professional */
    .metric-card {
        background-color: #0E1117 !important;
        border: 1px solid #303030 !important;
        border-radius: 8px;
        padding: 1.5rem;
        margin: 0.5rem 0;
    }
    
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
        color: #FAFAFA !important;
        font-family: system-ui, -apple-system, sans-serif;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #0E1117;
        border-right: 1px solid #303030;
    }
    
    /* Typography - System fonts */
    h1, h2, h3, h4, h5, h6, p, div, span, label {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    
    /* Header styling */
    h1, h2, h3 {
        color: #FAFAFA !important;
    }
    
    /* Button styling */
    .stButton > button {
        background-color: #262730;
        color: #FAFAFA;
        border: 1px solid #303030;
        border-radius: 6px;
        padding: 0.5rem 1.5rem;
        font-weight: 500;
        font-family: system-ui, -apple-system, sans-serif;
        transition: background-color 0.2s ease;
    }
    
    .stButton > button:hover {
        background-color: #303030;
        border-color: #404040;
    }
    
    /* Input fields */
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input,
    .stSelectbox > div > div > select {
        background-color: #0E1117;
        border: 1px solid #303030;
        color: #FAFAFA;
        border-radius: 6px;
        font-family: system-ui, -apple-system, sans-serif;
    }
    
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus,
    .stSelectbox > div > div > select:focus {
        border-color: #404040;
    }
    
    /* Dataframe styling */
    .dataframe {
        background-color: #0E1117;
        border: 1px solid #303030;
        border-radius: 6px;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Markdown text color */
    .stMarkdown {
        color: #FAFAFA;
    }
    
    /* Info boxes */
    [data-baseweb="notification"] {
        background-color: #262730 !important;
        border: 1px solid #303030 !important;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

# Inject CSS on app load
inject_custom_css()

# ============================================================================
# CSV PERSISTENCE - DATA ENGINE
# ============================================================================

def initialize_csv_file():
    """
    Initialize expenses.csv file if it doesn't exist.
    Creates CSV with required columns: Date, Category, Sub-Category, Amount, Description
    """
    if not os.path.exists(CSV_FILE):
        try:
            # Create empty DataFrame with required columns
            empty_df = pd.DataFrame(columns=['Date', 'Category', 'Sub-Category', 'Amount', 'Description'])
            # Save to CSV
            empty_df.to_csv(CSV_FILE, index=False)
            return empty_df
        except Exception as e:
            st.error(f"Error initializing CSV file: {str(e)}")
            return pd.DataFrame(columns=['Date', 'Category', 'Sub-Category', 'Amount', 'Description'])
    return None

def load_expenses_from_csv():
    """
    Load expenses data from expenses.csv file.
    This is the PERSISTENCE function that reads from disk on app startup.
    
    Returns:
        pd.DataFrame: Expenses data loaded from CSV
    """
    try:
        # Initialize if file doesn't exist
        initialize_csv_file()
        
        # Load from CSV
        if os.path.exists(CSV_FILE):
            df = pd.read_csv(CSV_FILE)
            # Convert Date column to datetime
            if 'Date' in df.columns and not df.empty:
                df['Date'] = pd.to_datetime(df['Date'])
            return df
        else:
            return pd.DataFrame(columns=['Date', 'Category', 'Sub-Category', 'Amount', 'Description'])
    except Exception as e:
        st.error(f"Error loading expenses from CSV: {str(e)}")
        return pd.DataFrame(columns=['Date', 'Category', 'Sub-Category', 'Amount', 'Description'])

def save_expenses_to_csv(df):
    """
    Save expenses DataFrame to expenses.csv file.
    This is the PERSISTENCE function that writes changes to disk immediately.
    
    Args:
        df (pd.DataFrame): Expenses DataFrame to save
    """
    try:
        # Ensure Date column is formatted correctly for CSV
        df_to_save = df.copy()
        if 'Date' in df_to_save.columns and not df_to_save.empty:
            df_to_save['Date'] = pd.to_datetime(df_to_save['Date']).dt.strftime('%Y-%m-%d')
        
        # Save to CSV
        df_to_save.to_csv(CSV_FILE, index=False)
    except Exception as e:
        st.error(f"Error saving expenses to CSV: {str(e)}")

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

def initialize_session_state():
    """
    Initialize session_state with data from CSV (persistence).
    Also initialize other app state variables.
    """
    if 'expenses' not in st.session_state:
        # Load from CSV (persistence load)
        st.session_state.expenses = load_expenses_from_csv()
    
    if 'bank_balance' not in st.session_state:
        st.session_state.bank_balance = 0.0
    
    if 'stock_cache' not in st.session_state:
        st.session_state.stock_cache = {}
    
    if 'stock_cache_time' not in st.session_state:
        st.session_state.stock_cache_time = {}

# Initialize on app start
initialize_session_state()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_currency(amount):
    """Format amount as Indian Rupees."""
    return f"₹{amount:,.2f}"

def get_cached_stock_price(ticker):
    """
    Get stock price with caching (5 minutes).
    Checks cache first, fetches from API if cache expired or missing.
    Includes error handling to prevent app crashes.
    
    Args:
        ticker (str): Stock ticker symbol
        
    Returns:
        float: Current stock price, or None if unavailable
    """
    current_time = time.time()
    
    # Check cache validity
    if (ticker in st.session_state.stock_cache and 
        ticker in st.session_state.stock_cache_time):
        cache_age = current_time - st.session_state.stock_cache_time[ticker]
        if cache_age < STOCK_CACHE_DURATION:
            # Return cached value
            return st.session_state.stock_cache[ticker]
    
    # Cache expired or missing - fetch from API
    if not YFINANCE_AVAILABLE:
        return None
    
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="1d")
        if not data.empty:
            price = float(data['Close'].iloc[-1])
            # Update cache
            st.session_state.stock_cache[ticker] = price
            st.session_state.stock_cache_time[ticker] = current_time
            return price
    except Exception as e:
        # Silently fail - return None (will show fallback in UI)
        return None
    
    return None

def calculate_portfolio_value():
    """
    Calculate total portfolio value from live ticker prices.
    Uses cached stock prices for performance.
    
    Returns:
        float: Total portfolio value
    """
    total_value = 0.0
    
    for ticker in LIVE_TICKERS:
        price = get_cached_stock_price(ticker)
        if price:
            # For demo: assume 10 shares of each stock
            # In production, this would come from a portfolio CSV or database
            quantity = 10
            total_value += price * quantity
    
    return total_value

def calculate_monthly_expenses(df):
    """
    Calculate total expenses for current month.
    
    Args:
        df (pd.DataFrame): Expenses DataFrame
        
    Returns:
        float: Total monthly expenses
    """
    if df.empty or 'Date' not in df.columns:
        return 0.0
    
    try:
        current_month = datetime.now().strftime('%Y-%m')
        df['Month'] = pd.to_datetime(df['Date']).dt.to_period('M').astype(str)
        monthly_expenses = df[df['Month'] == current_month]['Amount'].sum()
        return float(monthly_expenses)
    except Exception as e:
        return 0.0

# ============================================================================
# MAIN APP LAYOUT
# ============================================================================

# Title
st.title("💰 WealthOS")
st.markdown("---")

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Bank Balance Input
    bank_balance = st.number_input(
        "Current Bank Balance (₹)",
        min_value=0.0,
        value=float(st.session_state.bank_balance),
        step=1000.0,
        format="%.2f"
    )
    st.session_state.bank_balance = bank_balance
    
    st.markdown("---")
    
    # Add Transaction Form
    st.header("➕ Add Transaction")
    
    with st.form("add_transaction_form", clear_on_submit=True):
        transaction_date = st.date_input("Date", value=date.today())
        
        # Two-level category system
        category_type = st.selectbox("Type", options=list(CATEGORY_MAP.keys()))
        sub_category = st.selectbox(
            "Sub-Category", 
            options=CATEGORY_MAP[category_type]
        )
        
        amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0, format="%.2f")
        description = st.text_input("Description")
        
        submitted = st.form_submit_button("Add Transaction", use_container_width=True)
        
        if submitted:
            try:
                # Create new transaction row
                new_row = pd.DataFrame([{
                    'Date': pd.Timestamp(transaction_date),
                    'Category': category_type,
                    'Sub-Category': sub_category,
                    'Amount': amount,
                    'Description': description
                }])
                
                # Append to existing expenses
                st.session_state.expenses = pd.concat(
                    [st.session_state.expenses, new_row],
                    ignore_index=True
                )
                
                # Save to CSV immediately (PERSISTENCE - Add operation)
                save_expenses_to_csv(st.session_state.expenses)
                
                st.success("✅ Transaction added successfully!")
                time.sleep(0.5)  # Brief pause for visual feedback
                st.rerun()
            except Exception as e:
                st.error(f"Error adding transaction: {str(e)}")

# ============================================================================
# DASHBOARD METRICS
# ============================================================================

# Calculate metrics
monthly_spends = calculate_monthly_expenses(st.session_state.expenses)
portfolio_value = calculate_portfolio_value()
net_worth = st.session_state.bank_balance + portfolio_value

# Display metrics with clean, flat styling
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        f"""
        <div class="metric-card">
            <h3 style="color: #FAFAFA; margin: 0; font-size: 14px; font-weight: 500;">Total Spent (Month)</h3>
            <h2 style="color: #FAFAFA; margin: 10px 0; font-size: 28px; font-weight: 600;">{format_currency(monthly_spends)}</h2>
        </div>
        """,
        unsafe_allow_html=True
    )

with col2:
    st.markdown(
        f"""
        <div class="metric-card">
            <h3 style="color: #FAFAFA; margin: 0; font-size: 14px; font-weight: 500;">Portfolio Value</h3>
            <h2 style="color: #FAFAFA; margin: 10px 0; font-size: 28px; font-weight: 600;">{format_currency(portfolio_value)}</h2>
        </div>
        """,
        unsafe_allow_html=True
    )

with col3:
    st.markdown(
        f"""
        <div class="metric-card">
            <h3 style="color: #FAFAFA; margin: 0; font-size: 14px; font-weight: 500;">Net Worth</h3>
            <h2 style="color: #FAFAFA; margin: 10px 0; font-size: 28px; font-weight: 600;">{format_currency(net_worth)}</h2>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

# ============================================================================
# LIVE TICKER SECTION
# ============================================================================

st.markdown("### 📈 Live Market Ticker")
st.markdown("---")

# Fetch live prices for all tickers
ticker_data = []
for ticker in LIVE_TICKERS:
    price = get_cached_stock_price(ticker)
    if price:
        ticker_data.append({
            'Ticker': ticker.replace('.NS', ''),
            'Live Price (₹)': format_currency(price),
            'Price': price
        })
    else:
        ticker_data.append({
            'Ticker': ticker.replace('.NS', ''),
            'Live Price (₹)': 'Loading...',
            'Price': 0
        })

if ticker_data:
    ticker_df = pd.DataFrame(ticker_data)
    # Display as styled dataframe - keep use_container_width for dataframes
    st.dataframe(
        ticker_df[['Ticker', 'Live Price (₹)']],
        use_container_width=True,
        hide_index=True
    )

# ============================================================================
# VISUALIZATIONS
# ============================================================================

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 💸 Spending by Category")
    
    if not st.session_state.expenses.empty and 'Sub-Category' in st.session_state.expenses.columns:
        # Group by Sub-Category
        category_spending = st.session_state.expenses.groupby('Sub-Category')['Amount'].sum().reset_index()
        category_spending = category_spending.sort_values('Amount', ascending=False)
        
        if not category_spending.empty:
            fig_pie = px.pie(
                category_spending,
                values='Amount',
                names='Sub-Category',
                hole=0.4,
                template='plotly_dark',
                color_discrete_sequence=[PLOTLY_COLORS['neon_blue'], PLOTLY_COLORS['cyan'], PLOTLY_COLORS['purple'], '#FF00FF', '#00FF00']
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label', textfont_size=12)
            # Removed use_container_width=True to fix warning - Plotly auto-resizes by default
            st.plotly_chart(fig_pie, key="spending_pie_chart")
        else:
            st.info("No spending data available")
    else:
        st.info("No spending data available")

with col2:
    st.markdown("### 📊 Monthly Spending Trend")
    
    if not st.session_state.expenses.empty:
        try:
            # Create monthly trend
            expenses_copy = st.session_state.expenses.copy()
            expenses_copy['Month'] = pd.to_datetime(expenses_copy['Date']).dt.to_period('M').astype(str)
            monthly_trend = expenses_copy.groupby('Month')['Amount'].sum().reset_index()
            monthly_trend = monthly_trend.sort_values('Month')
            
            if not monthly_trend.empty:
                fig_bar = px.bar(
                    monthly_trend,
                    x='Month',
                    y='Amount',
                    template='plotly_dark',
                    color='Amount',
                    color_continuous_scale=['#00D9FF', '#B026FF']
                )
                fig_bar.update_layout(
                    yaxis_title='Amount (₹)',
                    xaxis_title='Month',
                    showlegend=False
                )
                # Removed use_container_width=True to fix warning - Plotly auto-resizes by default
                st.plotly_chart(fig_bar, key="monthly_trend_chart")
            else:
                st.info("No monthly trend data available")
        except Exception as e:
            st.info("No monthly trend data available")
    else:
        st.info("No monthly trend data available")

st.markdown("<br>", unsafe_allow_html=True)

# ============================================================================
# TRANSACTION EDITOR - CRUD OPERATIONS
# ============================================================================

st.markdown("### 📋 Transaction Log")
st.markdown("---")

st.info("💡 **Edit directly in the table below or delete rows. Changes save automatically to expenses.csv**")

if not st.session_state.expenses.empty:
    # Prepare display DataFrame - keep Date as datetime for DateColumn compatibility
    display_df = st.session_state.expenses.copy()
    
    # Ensure Date column is datetime type (not string) for DateColumn config
    if 'Date' in display_df.columns:
        display_df['Date'] = pd.to_datetime(display_df['Date'])
    
    # Use st.data_editor for inline editing and deletion - keep use_container_width for data_editor
    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        num_rows="dynamic",  # Allows adding/deleting rows
        column_config={
            'Date': st.column_config.DateColumn('Date'),
            'Category': st.column_config.SelectboxColumn(
                'Category',
                options=list(CATEGORY_MAP.keys())
            ),
            'Sub-Category': st.column_config.SelectboxColumn(
                'Sub-Category',
                options=sum(CATEGORY_MAP.values(), [])  # Flatten all sub-categories
            ),
            'Amount': st.column_config.NumberColumn('Amount (₹)', format="%.2f"),
            'Description': st.column_config.TextColumn('Description')
        },
        hide_index=True,
        key="expense_editor"
    )
    
    # Check if data was modified (CRUD - Edit/Delete operations)
    if not edited_df.equals(display_df):
        try:
            # Ensure Date is datetime format (data_editor returns datetime from DateColumn)
            if 'Date' in edited_df.columns:
                edited_df['Date'] = pd.to_datetime(edited_df['Date'])
            
            # Update session state
            st.session_state.expenses = edited_df
            
            # Save to CSV immediately (PERSISTENCE - Edit/Delete operation)
            save_expenses_to_csv(st.session_state.expenses)
            
            st.success("✅ Changes saved to expenses.csv!")
            time.sleep(0.5)
            st.rerun()
        except Exception as e:
            st.error(f"Error saving changes: {str(e)}")
else:
    st.info("No transactions yet. Add your first transaction using the sidebar form!")

# Footer
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: rgba(255,255,255,0.5);'>WealthOS © 2024 | Obsidian Edition</p>",
    unsafe_allow_html=True
)
