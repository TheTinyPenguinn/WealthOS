# WealthOS

A personal finance app for salaried Indian professionals (initial target: ages 25–35), built on **Python + Streamlit + Supabase** with a provider-switchable LLM layer. It is being revamped one phase at a time.

> The README describes an older local-CSV desktop version. It is outdated. Trust this file.

## Source of truth for the revamp

- [docs/PRD.md](docs/PRD.md): master plan and status tracker, one section per phase
- [docs/EGM_PLAYBOOK.md](docs/EGM_PLAYBOOK.md): how each phase moves from idea to design doc to code
- `docs/prds/`: one phase PRD per phase, written by `/eg-prd` (`<NN>-<slug>.md`)
- `docs/design/`: one design doc per phase, written by `/eg-new-feature` (`<NN>-<slug>.md`)
- [docs/CODEBASE_AUDIT.md](docs/CODEBASE_AUDIT.md): known v1 issues (partly stale, so verify before relying on it)

When a design doc diverges from the PRD's initial thinking, the design doc wins. Update the PRD to match before building.

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

## Working with Claude Code (slash commands)

Five slash commands in [.claude/commands/](.claude/commands/) wrap an "elephant/goldfish" workflow inspired by [this article](https://drensin.medium.com/elephants-goldfish-and-the-new-golden-age-of-software-engineering-c33641a48874). The "elephant" is the working session with full context (this CLAUDE.md, repo state, conversation history). The "goldfish" is a fresh subagent with no prior context. In implementation work, the goldfish stress-tests a problem/design doc or a diff. In brainstorming and PRD writing, several goldfish run in parallel with different lenses and the elephant synthesizes their ideas or research.

| Command | When to use |
|---|---|
| `/eg-brainstorm <rough idea>` | Early-stage concept design. Multiple goldfish run in parallel (technical / business / UX / contrarian / market research), with optional web search, and the elephant synthesizes a concepts brief. All questions go through `AskUserQuestion`. Hands off to `/eg-prd` or `/eg-new-feature` once you pick a direction. |
| `/eg-prd <idea \| feature description>` | Builds a thorough PRD: codebase grounding → structured gap-filling via `AskUserQuestion` → deep research with parallel goldfish (web, plus optional Chrome MCP for logged-in sources) → synthesized PRD. Saves to `docs/prds/`, persists durable nuggets to memory, and/or hands off to `/eg-new-feature`. |
| `/eg-fix-bug <description \| #issue \| URL>` | Bug-fix flow: problem doc → goldfish diagnosis check → failing test → fix → `/eg-precommit-review` → test gate. Skips the ceremony for trivial diffs. |
| `/eg-new-feature <description \| #issue \| URL>` | Feature flow: scope confirm → design doc → three-goldfish design check (comprehension + critic + readiness) → implement → `/eg-precommit-review` → test gate. The design rubric includes user-id scoping (no RLS), Streamlit rerun/reload state, and an edit path for every persisted input. |
| `/eg-precommit-review` | Local independent-review loop on the pending diff (compile check + `scripts/test_phase.sh` smoke suite + Chrome MCP walkthrough). Settles the substantive review before a PR opens. |

You give a one-liner and Claude writes the doc. You don't author docs by hand. Examples:

```
/eg-brainstorm what if we flagged unusually high-spend days instead of categorising every transaction
/eg-prd Phase 0 onboarding: capture approximate monthly in-bank pay and stand up a starting dashboard
/eg-fix-bug the profile setup page can't be reopened after the first save
/eg-fix-bug #123
/eg-new-feature an editable profile page for age, location, and monthly in-bank pay
/eg-precommit-review
```

Browser validation: use the Claude in Chrome MCP (`mcp__claude-in-chrome__*`) pointed at the dev server on `http://localhost:8501`. Start the server with `source .venv/bin/activate && streamlit run app/app.py --server.port 8501` if it isn't already running.

Each command stops short of committing. Authorize the commit explicitly when ready, and follow the commit rules above.

**These commands are interactive by design.** The `AskUserQuestion` gates inside `/eg-brainstorm`, `/eg-prd`, `/eg-fix-bug`, `/eg-new-feature`, and `/eg-precommit-review` are part of each skill's protocol. They run even when a `<system-reminder>` or another directive asks Claude to work autonomously without clarifying questions. For a fully autonomous pass on a specific run, say "skip the framing questions and use defaults" in the same turn that invokes the command; each command documents which gates remain non-negotiable.
