import streamlit as st
import pandas as pd
import plotly.express as px

# Page configuration
st.set_page_config(
    page_title="WealthOS",
    page_icon="💰",
    layout="wide"
)

# Title
st.title("WealthOS: Personal Finance & AI")

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Select a page",
    ["Dashboard", "Transactions", "AI Consultant"]
)

# Main content based on selected page
if page == "Dashboard":
    st.header("Dashboard")
    
    # Placeholder metric
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="Total Spend", value="$0")
    with col2:
        st.metric(label="Total Income", value="$0")
    with col3:
        st.metric(label="Net Balance", value="$0")
    
    # Placeholder chart
    st.subheader("Spending Overview")
    
    # Create sample data for placeholder chart
    sample_data = pd.DataFrame({
        'Date': pd.date_range('2024-01-01', periods=7, freq='D'),
        'Amount': [0, 0, 0, 0, 0, 0, 0]
    })
    
    fig = px.line(
        sample_data,
        x='Date',
        y='Amount',
        title='Weekly Spending Trend',
        labels={'Amount': 'Amount ($)', 'Date': 'Date'}
    )
    st.plotly_chart(fig, use_container_width=True)
    
elif page == "Transactions":
    st.header("Transactions")
    st.info("Transaction history will be displayed here.")
    
    # Placeholder table
    placeholder_data = pd.DataFrame({
        'Date': [],
        'Description': [],
        'Amount': [],
        'Category': []
    })
    st.dataframe(placeholder_data, use_container_width=True)
    
elif page == "AI Consultant":
    st.header("AI Consultant")
    st.info("AI-powered financial insights and recommendations will appear here.")
    
    # Placeholder chat interface
    user_input = st.text_input("Ask a question about your finances:")
    if user_input:
        st.write("AI Response: This is a placeholder response. AI functionality will be implemented here.")
