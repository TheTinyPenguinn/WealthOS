# 💰 WealthOS

A personal finance app for salaried professionals in India. It keeps income, spending, debt and investments in one place, and an LLM agent answers questions using those figures.

🔗 **Live app:** [wealthos-cfo.streamlit.app](https://wealthos-cfo.streamlit.app/)

![Status](https://img.shields.io/badge/Status-MVP-orange) ![Stack](https://img.shields.io/badge/Stack-Python%20%C2%B7%20Streamlit%20%C2%B7%20Supabase-blue)

> Early MVP, built solo. It runs end to end and is deployed, but it is not a finished product. Sign-up is open — use made-up figures rather than real bank data.

## What it does

**Dashboard** — opens with a suggested next action worked out from your own numbers, then where each month's pay goes (commitments, day-to-day spending, what's left), what you own minus what you owe, and where you're exposed: emergency fund, tax-saving allowance used, expensive debt, insurance cover.

**Transactions** — import a bank statement as CSV or PDF, or enter items by hand. Auto-categorisation with rules you can teach and override.

**Investments** — import Zerodha holdings, with live valuation and unrealised profit and loss.

**AI CFO** — an agent with tool access that reads your stored figures and answers questions about them: what a purchase does to your runway, whether to clear debt or invest a surplus. Conversations are saved, so you can go back and check the numbers it quoted. Falls back across model and provider when one is unavailable.

**Insurance** — suggested term and health cover sized from your pay, as rules of thumb.

**Goals** — emergency fund tracking and goal sequencing against monthly surplus.

**Tax** — placeholder. The tab describes what belongs there; none of it is built.

## Stack

Python · Streamlit · Supabase (auth and Postgres, row-level security on every user table) · pandas · Plotly · a switchable LLM layer (Gemini, OpenAI or Anthropic)

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

On a fresh Supabase project, run the files in `supabase_migrations/migrations/` in order, once each, in the Supabase SQL editor.

Checks: `bash scripts/test_phase.sh`

## Known gaps

Listed in [`docs/CODEBASE_AUDIT.md`](docs/CODEBASE_AUDIT.md). The main ones: transaction categorisation is unreliable on merchant names it hasn't seen, onboarding collects more than it uses, and imported statements are historical so recent-window figures can read as empty.
