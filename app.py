"""
WealthOS: Personal Finance & AI Dashboard
A comprehensive financial management application built with Streamlit.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date

# Optional import for yfinance (requires Python 3.10+ for type hints)
# If not available, stock prices will use fallback values
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except (ImportError, TypeError) as e:
    # Handle case where yfinance is not installed or incompatible with Python version
    YFINANCE_AVAILABLE = False
    yf = None
    if isinstance(e, TypeError):
        st.warning(
            "⚠️ yfinance requires Python 3.10+ for type hints. "
            "Stock prices will use estimated values. "
            "To enable real-time prices, upgrade to Python 3.10+ or install compatible yfinance version."
        )

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
# INITIALIZE SESSION STATE WITH DUMMY DATA
# ============================================================================

def initialize_session_state():
    """
    Initialize session_state with realistic dummy data if not already present.
    This ensures the app is populated immediately upon first run.
    """
    if 'expenses' not in st.session_state:
        # Pre-populate with 8-10 realistic expense transactions
        st.session_state.expenses = pd.DataFrame([
            {
                'Date': pd.Timestamp('2024-01-05'),
                'Amount': 4500.0,
                'Category': 'Groceries',
                'Description': 'Weekly grocery shopping'
            },
            {
                'Date': pd.Timestamp('2024-01-10'),
                'Amount': 25000.0,
                'Category': 'Rent',
                'Description': 'Monthly rent payment'
            },
            {
                'Date': pd.Timestamp('2024-01-12'),
                'Amount': 1200.0,
                'Category': 'Dining Out',
                'Description': 'Restaurant dinner'
            },
            {
                'Date': pd.Timestamp('2024-01-15'),
                'Amount': 800.0,
                'Category': 'Utilities',
                'Description': 'Electricity bill'
            },
            {
                'Date': pd.Timestamp('2024-01-18'),
                'Amount': 5000.0,
                'Category': 'SIPs',
                'Description': 'Monthly mutual fund SIP'
            },
            {
                'Date': pd.Timestamp('2024-01-20'),
                'Amount': 3500.0,
                'Category': 'Shopping',
                'Description': 'Online shopping'
            },
            {
                'Date': pd.Timestamp('2024-01-22'),
                'Amount': 1800.0,
                'Category': 'Medicine',
                'Description': 'Pharmacy expenses'
            },
            {
                'Date': pd.Timestamp('2024-01-25'),
                'Amount': 6000.0,
                'Category': 'Travel',
                'Description': 'Weekend trip'
            },
            {
                'Date': pd.Timestamp('2024-01-28'),
                'Amount': 2500.0,
                'Category': 'EMI',
                'Description': 'Home loan EMI'
            },
            {
                'Date': pd.Timestamp('2024-01-30'),
                'Amount': 1500.0,
                'Category': 'Entertainment',
                'Description': 'Movie tickets'
            }
        ])
    
    if 'investments' not in st.session_state:
        # Initialize with 3 Indian stock holdings
        st.session_state.investments = pd.DataFrame([
            {
                'Ticker': 'RELIANCE.NS',
                'Quantity': 10,
                'AvgBuyPrice': 2450.0
            },
            {
                'Ticker': 'TCS.NS',
                'Quantity': 25,
                'AvgBuyPrice': 3250.0
            },
            {
                'Ticker': 'INFY.NS',
                'Quantity': 30,
                'AvgBuyPrice': 1650.0
            }
        ])
    
    if 'income' not in st.session_state:
        # Store monthly income data
        st.session_state.income = 75000.0  # Default monthly income

# Call initialization function
initialize_session_state()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_currency(amount):
    """
    Format amount as Indian Rupees with proper formatting.
    
    Args:
        amount (float): The amount to format
        
    Returns:
        str: Formatted currency string
    """
    return f"₹{amount:,.2f}"

def get_stock_price(ticker):
    """
    Fetch real-time stock price using yfinance API.
    Includes error handling to prevent app crashes.
    Falls back to estimated prices if yfinance is not available.
    
    Args:
        ticker (str): Stock ticker symbol (e.g., 'RELIANCE.NS')
        
    Returns:
        float: Current stock price, or None if API call fails
    """
    # Check if yfinance is available
    if not YFINANCE_AVAILABLE:
        # Return None to trigger fallback in get_investment_portfolio
        return None
    
    try:
        stock = yf.Ticker(ticker)
        # Get the latest price (last close price)
        data = stock.history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
        else:
            return None
    except Exception as e:
        # Log error but don't crash the app
        st.warning(f"Could not fetch price for {ticker}: {str(e)}")
        return None

def get_investment_portfolio():
    """
    Calculate current portfolio value by fetching live stock prices.
    Returns a dataframe with all portfolio metrics.
    
    Returns:
        pd.DataFrame: Portfolio data with Current Price, Current Value, P/L
    """
    portfolio_df = st.session_state.investments.copy()
    
    current_prices = []
    current_values = []
    pl_amounts = []
    pl_percentages = []
    
    for _, row in portfolio_df.iterrows():
        ticker = row['Ticker']
        qty = row['Quantity']
        avg_price = row['AvgBuyPrice']
        
        # Fetch live price (with fallback)
        live_price = get_stock_price(ticker)
        
        if live_price is None:
            # Use average buy price as fallback if API fails
            live_price = avg_price
        
        current_prices.append(live_price)
        current_value = qty * live_price
        current_values.append(current_value)
        
        # Calculate P/L
        total_invested = qty * avg_price
        pl_amount = current_value - total_invested
        pl_amounts.append(pl_amount)
        pl_percentages.append((pl_amount / total_invested * 100) if total_invested > 0 else 0)
    
    portfolio_df['LivePrice'] = current_prices
    portfolio_df['CurrentValue'] = current_values
    portfolio_df['P/L'] = pl_amounts
    portfolio_df['P/L%'] = pl_percentages
    
    return portfolio_df

def calculate_monthly_expenses(month_filter):
    """
    Calculate total expenses for the selected month.
    
    Args:
        month_filter (str): Month in 'YYYY-MM' format
        
    Returns:
        float: Total expenses for the month
    """
    if st.session_state.expenses.empty:
        return 0.0
    
    expenses_df = st.session_state.expenses.copy()
    expenses_df['Month'] = pd.to_datetime(expenses_df['Date']).dt.to_period('M').astype(str)
    
    monthly_expenses = expenses_df[expenses_df['Month'] == month_filter]['Amount'].sum()
    return float(monthly_expenses)

def calculate_net_worth():
    """
    Calculate net worth: Total Investments - Total Liabilities.
    
    Returns:
        float: Net worth value
    """
    # Get total investment value
    portfolio_df = get_investment_portfolio()
    total_investments = portfolio_df['CurrentValue'].sum()
    
    # Calculate total liabilities (EMIs, loans)
    if st.session_state.expenses.empty:
        total_liabilities = 0.0
    else:
        liabilities_categories = ['EMI', 'Insurance']  # Categories that represent liabilities
        liabilities_df = st.session_state.expenses[
            st.session_state.expenses['Category'].isin(liabilities_categories)
        ]
        # For simplicity, we'll use monthly EMI * 12 as annual liability estimate
        monthly_liabilities = liabilities_df['Amount'].sum()
        total_liabilities = monthly_liabilities * 12  # Annual estimate
    
    return total_investments - total_liabilities

def calculate_savings_rate(month_filter):
    """
    Calculate savings rate as percentage of income.
    
    Args:
        month_filter (str): Month in 'YYYY-MM' format
        
    Returns:
        float: Savings rate percentage
    """
    monthly_income = st.session_state.income
    monthly_expenses = calculate_monthly_expenses(month_filter)
    
    if monthly_income == 0:
        return 0.0
    
    savings = monthly_income - monthly_expenses
    savings_rate = (savings / monthly_income) * 100
    return savings_rate

# ============================================================================
# SIDEBAR NAVIGATION & FILTERS
# ============================================================================

st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Select a page",
    ["Dashboard", "Expense Tracker", "Investment Portfolio", "Liabilities", "AI Consultant"]
)

# Global Month Filter
st.sidebar.markdown("---")
st.sidebar.subheader("Filters")

# Get current month as default
current_month = datetime.now().strftime('%Y-%m')
selected_month = st.sidebar.selectbox(
    "Select Month",
    options=pd.date_range(start='2023-01-01', end='2024-12-31', freq='M').strftime('%Y-%m').tolist(),
    index=len(pd.date_range(start='2023-01-01', end='2024-12-31', freq='M').strftime('%Y-%m').tolist()) - 1
)

# ============================================================================
# MAIN PAGE: DASHBOARD
# ============================================================================

if page == "Dashboard":
    st.title("WealthOS: Personal Finance & AI")
    st.header("Dashboard")
    
    # Calculate key metrics
    net_worth = calculate_net_worth()
    monthly_spends = calculate_monthly_expenses(selected_month)
    savings_rate = calculate_savings_rate(selected_month)
    
    # Top Row: 3 Key Metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            label="Net Worth",
            value=format_currency(net_worth),
            delta=None
        )
    
    with col2:
        st.metric(
            label="Monthly Spends",
            value=format_currency(monthly_spends),
            delta=None
        )
    
    with col3:
        st.metric(
            label="Savings Rate",
            value=f"{savings_rate:.1f}%",
            delta=None
        )
    
    st.markdown("---")
    
    # Visualizations Row
    col1, col2 = st.columns(2)
    
    with col1:
        # Donut Chart: Spends by Category
        st.subheader("Spends by Category")
        
        if not st.session_state.expenses.empty:
            expenses_df = st.session_state.expenses.copy()
            expenses_df['Month'] = pd.to_datetime(expenses_df['Date']).dt.to_period('M').astype(str)
            monthly_expenses_df = expenses_df[expenses_df['Month'] == selected_month]
            
            if not monthly_expenses_df.empty:
                category_totals = monthly_expenses_df.groupby('Category')['Amount'].sum().reset_index()
                
                fig_donut = px.pie(
                    category_totals,
                    values='Amount',
                    names='Category',
                    hole=0.4,
                    title=f"Spending Distribution ({selected_month})"
                )
                fig_donut.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig_donut, use_container_width=True)
            else:
                st.info(f"No expenses recorded for {selected_month}")
        else:
            st.info("No expenses data available")
    
    with col2:
        # Bar Chart: Income vs Expense Trend
        st.subheader("Income vs Expense Trend")
        
        # Create trend data for last 6 months
        months_list = pd.date_range(end=selected_month, periods=6, freq='M').strftime('%Y-%m').tolist()
        trend_data = []
        
        for month in months_list:
            expenses = calculate_monthly_expenses(month)
            trend_data.append({
                'Month': month,
                'Income': st.session_state.income,
                'Expenses': expenses
            })
        
        trend_df = pd.DataFrame(trend_data)
        
        fig_bar = px.bar(
            trend_df,
            x='Month',
            y=['Income', 'Expenses'],
            barmode='group',
            title="Monthly Income vs Expenses",
            labels={'value': 'Amount (₹)', 'variable': 'Type'}
        )
        st.plotly_chart(fig_bar, use_container_width=True)

# ============================================================================
# EXPENSE TRACKER PAGE
# ============================================================================

elif page == "Expense Tracker":
    st.title("WealthOS: Personal Finance & AI")
    st.header("Expense Tracker")
    
    # Hardcoded Categories
    expense_categories = {
        'Essentials': ['Groceries', 'Rent', 'Medicine', 'Utilities'],
        'Lifestyle': ['Dining Out', 'Travel', 'Shopping', 'Entertainment'],
        'Financial': ['SIPs', 'EMI', 'Insurance']
    }
    
    all_categories = [cat for sublist in expense_categories.values() for cat in sublist]
    
    # Form to Add New Transaction
    with st.form("add_expense_form", clear_on_submit=True):
        st.subheader("Add New Transaction")
        
        col1, col2 = st.columns(2)
        
        with col1:
            transaction_date = st.date_input("Date", value=date.today())
            amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0, format="%.2f")
        
        with col2:
            category = st.selectbox("Category", options=all_categories)
            description = st.text_input("Description")
        
        submitted = st.form_submit_button("Add Transaction")
        
        if submitted:
            # Add transaction to session state
            new_transaction = pd.DataFrame([{
                'Date': pd.Timestamp(transaction_date),
                'Amount': amount,
                'Category': category,
                'Description': description
            }])
            
            st.session_state.expenses = pd.concat(
                [st.session_state.expenses, new_transaction],
                ignore_index=True
            )
            st.success("Transaction added successfully!")
    
    st.markdown("---")
    
    # Display Transaction Log
    st.subheader("Transaction History")
    
    if not st.session_state.expenses.empty:
        # Display full transaction log
        display_df = st.session_state.expenses.copy()
        display_df = display_df.sort_values('Date', ascending=False)
        display_df['Date'] = display_df['Date'].dt.date
        display_df['Amount'] = display_df['Amount'].apply(lambda x: format_currency(x))
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
        
        # Show summary statistics
        st.markdown("### Summary Statistics")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Transactions", len(st.session_state.expenses))
        with col2:
            st.metric("Total Spent", format_currency(st.session_state.expenses['Amount'].sum()))
        with col3:
            st.metric("Average per Transaction", 
                     format_currency(st.session_state.expenses['Amount'].mean()))
    else:
        st.info("No transactions recorded yet. Add your first transaction using the form above.")

# ============================================================================
# INVESTMENT PORTFOLIO PAGE
# ============================================================================

elif page == "Investment Portfolio":
    st.title("WealthOS: Personal Finance & AI")
    st.header("Investment Portfolio")
    
    if YFINANCE_AVAILABLE:
        st.info("🔄 Fetching real-time stock prices... This may take a moment.")
    else:
        st.warning("⚠️ Real-time stock prices unavailable. Showing estimated values based on average buy price. Upgrade to Python 3.10+ for live prices.")
    
    # Get portfolio with live prices
    portfolio_df = get_investment_portfolio()
    
    if not portfolio_df.empty:
        # Display Portfolio Table
        st.subheader("Portfolio Holdings")
        
        # Format display dataframe
        display_portfolio = portfolio_df.copy()
        display_portfolio['AvgBuyPrice'] = display_portfolio['AvgBuyPrice'].apply(format_currency)
        display_portfolio['LivePrice'] = display_portfolio['LivePrice'].apply(format_currency)
        display_portfolio['CurrentValue'] = display_portfolio['CurrentValue'].apply(format_currency)
        display_portfolio['P/L'] = display_portfolio['P/L'].apply(format_currency)
        display_portfolio['P/L%'] = display_portfolio['P/L%'].apply(lambda x: f"{x:.2f}%")
        
        # Rename columns for display
        display_portfolio.columns = ['Ticker', 'Quantity', 'Avg Buy Price', 'Live Price', 
                                     'Current Value', 'P/L (₹)', 'P/L (%)']
        
        st.dataframe(
            display_portfolio,
            use_container_width=True,
            hide_index=True
        )
        
        # Total Portfolio Value Metric
        total_portfolio_value = portfolio_df['CurrentValue'].sum()
        st.markdown("---")
        st.metric(
            label="Total Portfolio Value",
            value=format_currency(total_portfolio_value),
            delta=None
        )
        
        # Portfolio Summary
        total_invested = (portfolio_df['Quantity'] * portfolio_df['AvgBuyPrice']).sum()
        total_pl = portfolio_df['P/L'].sum()
        total_pl_percent = (total_pl / total_invested * 100) if total_invested > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Invested", format_currency(total_invested))
        with col2:
            st.metric("Total P/L", format_currency(total_pl))
        with col3:
            st.metric("Total P/L %", f"{total_pl_percent:.2f}%")
    else:
        st.info("No investments in portfolio. Add stocks to start tracking.")

# ============================================================================
# LIABILITIES PAGE
# ============================================================================

elif page == "Liabilities":
    st.title("WealthOS: Personal Finance & AI")
    st.header("Liabilities")
    
    if not st.session_state.expenses.empty:
        # Filter for liability-related transactions
        liability_categories = ['EMI', 'Insurance']
        liabilities_df = st.session_state.expenses[
            st.session_state.expenses['Category'].isin(liability_categories)
        ].copy()
        
        if not liabilities_df.empty:
            st.subheader("Liability Transactions")
            
            display_liabilities = liabilities_df.copy()
            display_liabilities = display_liabilities.sort_values('Date', ascending=False)
            display_liabilities['Date'] = display_liabilities['Date'].dt.date
            display_liabilities['Amount'] = display_liabilities['Amount'].apply(format_currency)
            
            st.dataframe(
                display_liabilities,
                use_container_width=True,
                hide_index=True
            )
            
            # Summary
            monthly_liabilities = liabilities_df['Amount'].sum()
            annual_liabilities = monthly_liabilities * 12
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Monthly Liabilities", format_currency(monthly_liabilities))
            with col2:
                st.metric("Estimated Annual Liabilities", format_currency(annual_liabilities))
        else:
            st.info("No liability transactions recorded. Liabilities include EMI and Insurance payments.")
    else:
        st.info("No expense data available.")

# ============================================================================
# AI CONSULTANT PAGE
# ============================================================================

elif page == "AI Consultant":
    st.title("WealthOS: Personal Finance & AI")
    st.header("AI Consultant")
    
    st.info("🤖 AI-powered financial insights and recommendations")
    
    # Initialize chat history in session state
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
        
        # Pre-fill with a mock system message
        if not st.session_state.expenses.empty:
            expenses_df = st.session_state.expenses.copy()
            
            # Analyze spending patterns
            top_category = expenses_df.groupby('Category')['Amount'].sum().idxmax()
            top_category_spend = expenses_df.groupby('Category')['Amount'].sum().max()
            
            system_message = (
                f"I've analyzed your spending patterns. I noticed your '{top_category}' "
                f"expenses are highest at {format_currency(top_category_spend)}. "
                f"Consider reviewing this category to optimize your savings. "
                f"Your current monthly spending is {format_currency(expenses_df['Amount'].sum())}. "
                f"Would you like suggestions on how to reduce expenses?"
            )
            
            st.session_state.chat_history.append({
                'role': 'assistant',
                'content': system_message
            })
    
    # Display chat history
    for message in st.session_state.chat_history:
        with st.chat_message(message['role']):
            st.write(message['content'])
    
    # Chat input
    user_input = st.chat_input("Ask a question about your finances...")
    
    if user_input:
        # Add user message to history
        st.session_state.chat_history.append({
            'role': 'user',
            'content': user_input
        })
        
        # Display user message
        with st.chat_message('user'):
            st.write(user_input)
        
        # Generate AI response (placeholder)
        ai_response = (
            "Thank you for your question. This is a placeholder response. "
            "Full AI integration with financial analysis capabilities will be implemented in the next version. "
            "For now, you can review your dashboard metrics and expense tracker for insights."
        )
        
        # Add AI response to history
        st.session_state.chat_history.append({
            'role': 'assistant',
            'content': ai_response
        })
        
        # Display AI response
        with st.chat_message('assistant'):
            st.write(ai_response)
        
        # Rerun to update the chat display
        st.rerun()
