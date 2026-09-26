# 💰 WealthOS

**An AI-native personal finance app for salaried Indian professionals** — built to prescribe one action, not to draw more pie charts.

Most finance apps classify spending and leave you to work out what to do. WealthOS is an experiment in the opposite: reason across income, debt and investments, and say what to do next — pause a SIP, clear the 36% card first, hold the surplus.

🔗 **Live app:** [wealthos.streamlit.app](https://wealthos.streamlit.app)

![Status](https://img.shields.io/badge/Status-MVP%20%2F%20experimental-orange) ![Stack](https://img.shields.io/badge/Stack-Python%20%C2%B7%20Streamlit%20%C2%B7%20Supabase-blue)

> **Status: early MVP, built solo.** It works end to end and is deployed, but it's a personal experiment rather than a finished product, and parts of it are mid-rebuild. Treat it as a prototype for the product thinking in [`docs/`](docs/), not a bank-grade tool.

## What it does today

- **Unified ledger** — accounts, fixed costs, obligations, investments and expenses in one place
- **Imports** — bank statement CSVs, Zerodha exports, and receipt/statement parsing
- **AI CFO** — an LLM agent with tool access that reasons over your actual numbers (debt cost vs. expected return, surplus, runway)
- **Tax** — 80C tracking, old vs. new regime comparison, capital gains, a CA-ready export
- **Insurance** — policy inventory, coverage gaps, endowment-trap detection
- **Goals** — emergency-fund ring-fencing, goal sequencing, and a "freedom score"

## Stack

Python · Streamlit (UI) · Supabase (auth + Postgres) · pandas/plotly · a switchable LLM layer (Gemini, OpenAI or Anthropic)

## Run it locally

```bash
git clone https://github.com/TheTinyPenguinn/WealthOS.git
cd WealthOS

python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env    # then fill it in, see below
streamlit run app/app.py
```

`.env` needs your own Supabase project and one LLM key:

```
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_ANON_KEY=<your anon key>
LLM_PROVIDER=gemini          # gemini | openai | anthropic
GEMINI_API_KEY=<your key>    # or OPENAI_API_KEY / ANTHROPIC_API_KEY
```

On a fresh Supabase project, run `supabase_migrations/migrations/001_wealthos_phase_tables.sql` once in the Supabase SQL editor to create the tables.

## Known gaps

Documented honestly in [`docs/CODEBASE_AUDIT.md`](docs/CODEBASE_AUDIT.md): onboarding collects more than it uses, some inputs aren't persisted, and transaction categorisation is unreliable. Row-level security is enabled on every user table.
