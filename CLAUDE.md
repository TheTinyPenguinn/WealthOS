# WealthOS

A personal finance app for salaried Indian professionals (initial target: ages 25–35), built on **Python + Streamlit + Supabase** with a provider-switchable LLM layer.

## Known issues

[docs/CODEBASE_AUDIT.md](docs/CODEBASE_AUDIT.md) lists them, and is partly stale — verify against the code before relying on it.

## Run

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/app.py --server.port 8501
```

Config comes from `.env` (template: `.env.example`): `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `LLM_PROVIDER`, and the matching provider key. `app/db.py` loads `.env` itself and falls back to `.streamlit/secrets.toml`. On Streamlit Cloud, the main file path must be `app/app.py`.

## Checks

```bash
source .venv/bin/activate && bash scripts/test_phase.sh
```

A 12-step smoke suite: compile checks plus contract checks for each domain module. Step 12 only pings `:8514` and warns if nothing answers; it never fails the run. There is no pytest suite, linter, or type checker.

## Architecture

- `app/app.py`: the entire Streamlit UI (~2.9k lines). It covers auth tabs, the first-time profile gate (app/app.py:1245), and the main tabs Dashboard / Transactions / Investments / AI Brain / Tax / Insurance / Goals (app/app.py:1606)
- `app/db.py`: Supabase client, all data access, and the env/secrets loader
- `app/utils/llm_client.py`: LLM client; the provider is picked by `LLM_PROVIDER` (gemini / openai / anthropic)
- `ai/agent.py`, `ai/tools.py`: the CFO agent and its tool dispatch
- `app/tax/`, `app/insurance/`, `app/goals/`, `app/scoring/`, `app/ingestion/`, `app/data_providers/`, `app/utils/`: domain modules
- `supabase_migrations/migrations/`: SQL applied to the Supabase project by hand

## Always check

- **Every Supabase read and write is scoped by the logged-in `user_id`.** RLS is enabled with owner-only policies on every user table (migrations 001 and 002), so a missing filter returns nothing rather than another user's rows — scope queries anyway, and never rely on RLS alone.
- **Every user input is either persisted or explicitly declared not persisted, and everything persisted has an edit path.** v1 onboarding broke both rules.
- Streamlit reruns the whole script on each interaction, `st.session_state` is lost on page reload, and an `st.stop()` gate can make a page unreachable.
- No pandas NaN/None or numpy types in Supabase payloads.
- Don't create top-level directories named like installed packages. A `supabase/` folder once shadowed `import supabase`.

## Commits

Imperative subject, a body that explains why, and a `Co-Authored-By` trailer. Never commit personal or career material (`deck.md` is gitignored), `.env`, or `secrets.toml`.
