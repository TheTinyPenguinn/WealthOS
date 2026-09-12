# 💰 WealthOS: The Personal CFO

**WealthOS** is a privacy-first, desktop-based Financial Operating System. Unlike Mint or Monarch, it runs locally on your machine, keeps your data in local CSVs, and uses AI (Gemini) to act as a ruthless Strategic CFO for debt and surplus optimization.

![Status](https://img.shields.io/badge/Status-Alpha-orange) ![Stack](https://img.shields.io/badge/Stack-Python_Streamlit-blue)

## 🚀 Why WealthOS?
* **Privacy First:** Your bank data never leaves your laptop (Local CSV storage).
* **AI CFO:** A customized AI agent that analyzes "Burn Rate," "Runway," and "Debt Arbitrage."
* **Zero-Install Sharing:** Can be compiled into a single `.exe` file.

## 🛠️ Installation (For Developers)
If you want to modify the code or run it from source:

### 1. Prerequisites
* **Python 3.10+** (Make sure to "Add to PATH" during install).
* **Gemini API Key** (Get a free key from Google AI Studio).

### 2. Setup
```bash
# Clone the repo
git clone [https://github.com/YOUR_USERNAME/WealthOS.git](https://github.com/YOUR_USERNAME/WealthOS.git)
cd WealthOS

# Create Virtual Environment
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

# Install Dependencies
pip install -r requirements.txt
