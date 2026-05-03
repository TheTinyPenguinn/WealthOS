## What Each File Does

- `app/app.py`
  - Main Streamlit WealthOS app (UI + business logic).
  - Handles auth (login/signup) via Supabase Auth.
  - Loads/syncs user data via `db.py` wrappers.
  - Provides tabs for dashboard, transactions, investments, and AI advisor.
  - Includes CSV parsers (bank statements, Zerodha exports), auto-categorization, and portfolio valuation.

- `app/db.py`
  - Supabase data access layer.
  - Initializes Supabase client from Streamlit secrets.
  - Loads all user tables into pandas DataFrames.
  - Provides snapshot sync functions for accounts/fixed costs/obligations/investments/expenses.
  - Persists user settings and feedback.

- `app/migrate.py`
  - One-time CLI migration script from local CSV/JSON files into Supabase tables.
  - Authenticates user, then migrates settings/accounts/fixed_costs/obligations/investments/expenses.
  - Uses service role key input during migration.

- `scripts/run.py`
  - Bootstraps Streamlit runtime (useful for frozen/PyInstaller execution).
  - Applies SSL cert workaround in frozen mode and launches Streamlit CLI programmatically.

- `scripts/hook-streamlit.py`
  - PyInstaller hook file.
  - Copies Streamlit package metadata into bundled artifact.

## What Works

- End-to-end cloud persistence flow is implemented:
  - Auth -> load data -> edit in UI -> sync back to Supabase.
- Core financial data model is coherent across app and DB wrapper:
  - Accounts, fixed costs, obligations, investments, expenses, settings.
- Batch inserts for large expenses payloads (500-row chunks) exist in multiple write paths.
- Zerodha import includes practical header detection and basic asset-type normalization.
- App has defensive wrappers for optional dependencies (`yfinance`, `openpyxl`, plotly, Gemini libs).
- Session-state based UX is reasonably resilient for Streamlit reruns.

## What Is Broken

- **Path break introduced by restructure unless launch command is updated**
  - `scripts/run.py` now points to `app/app.py` (fixed in this reorg), but direct commands like `streamlit run app.py` from repo root will fail because `app.py` moved under `app/`.

- **Supabase key naming mismatch**
  - `app/db.py` expects `st.secrets["SUPABASE_KEY"]`.
  - Requested env naming uses `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY`.
  - Without mapping, app can fail at startup with missing credentials.

- **Gemini key naming mismatch**
  - `app/app.py` fallback reads `st.secrets.get("GEMINI_KEY", "")`.
  - Requested env template uses `GEMINI_API_KEY`.
  - Fallback path will be empty unless secret names are aligned.

- **AI SDK inconsistency**
  - App conditionally imports `from google import genai` near top, but actual runtime generation uses `import google.generativeai as genai`.
  - This can create false-positive "available" checks and confusing dependency behavior.

- **Known market-data limitation for Indian Mutual Funds**
  - yfinance path does not reliably support Indian MF NAV by ticker.
  - Current code attempts MF NAV via `mfapi.in` using ISIN-like ticker; non-ISIN or malformed tickers silently fall back to avg buy price.
  - Result: portfolio can appear stable even when live NAV fetch fails.

- **`analyze_subscriptions()` recurring-month logic is buggy**
  - Uses `pd.to_datetime(...).dt.to_period('M')` on array-like values; this can fail because `.dt` accessor is not valid on `DatetimeIndex` in that flow.
  - Wrapped by broad `except`, so function often returns empty output instead of detected subscriptions.

- **Migration source expectations are mixed/legacy**
  - `app/migrate.py` reads from `data/*.csv` + `data/settings.json`, while investments/expenses are now under `data_samples/`.
  - This was partially adapted in reorg with fallback path resolution, but legacy assumptions remain.

- **Feedback timestamp payload may be invalid depending on DB schema**
  - `app/db.py` sends `"created_at": "now()"` as a literal string.
  - If column type requires timestamp and no DB trigger/default handles it, insert may fail.

## All Supabase Tables Used

- `user_settings`
- `accounts`
- `fixed_costs`
- `obligations`
- `investments`
- `expenses`
- `feedback`

## All Environment Variables Required

Based on current code behavior:

- `SUPABASE_URL`
  - Required by `app/db.py` client initialization.
- `SUPABASE_KEY`
  - Required by current `app/db.py` (expects this exact key name in Streamlit secrets).
- `GEMINI_KEY`
  - Optional fallback in current `app/app.py` if user-specific API key is not saved in DB.

Also recommended for your target standardization (created in `.env.example`):

- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`

Note: the app currently reads secrets via `st.secrets`, not `os.getenv()`. To use `.env` directly, code changes are needed.
