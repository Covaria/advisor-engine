# CLAUDE.md

Guidance for Claude (and anyone else) working in this repository. README.md is the
user-facing guide; this file covers how the code is put together and the rules to keep
when extending it.

## What this project is

A prototype decision-support engine for financial advisors. Given a holdings CSV it
computes a risk profile (effective independent bets, market-adjusted and sector-level
concentration, sector exposure, drawdown sensitivity, per-position risk). An LLM layer
explains those results in plain language, and a Streamlit app wraps both for demos.

**The core rule: the engine computes every number; the LLM never does.** The model only
calls engine tools and explains their output. Code enforces this (see "Number check"
below) rather than trusting the prompt. Any change that lets a figure reach the advisor
without coming from the engine breaks the product's main guarantee.

Current status: MVP step 2 (risk profile). Returns are synthetic until licensed market
data is confirmed.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # engine + pytest
pip install -e ".[dev,llm,ui,api]" # everything (anthropic, streamlit, fastapi)

pytest                             # full suite; never calls the real API
pytest tests/test_risk.py -q       # one file
python -m advisor_engine.demo      # print the sample risk profile as JSON
python -m advisor_engine.assistant [--holdings data/<file>.csv]   # terminal chat
streamlit run src/advisor_engine/ui/app.py                         # demo UI, :8501
uvicorn advisor_engine.api.main:app --reload                       # API, :8000 (dev auth)
```

Requires Python >= 3.10. `tests/test_ui.py` is skipped if Streamlit isn't installed.

## Layout

```
src/advisor_engine/
    __init__.py        __version__ (engine version recorded in every audit line)
    holdings.py        load/validate holdings CSV -> adds value and weight columns
    synthetic.py       market + sector factor model returns (stand-in for real data)
    risk.py            all risk math; risk_profile() -> RiskProfile.to_dict()
    demo.py            end-to-end run on data/sample/sample_holdings.csv
    assistant/
        _paths.py      REPO_ROOT, DATA_DIR, DEFAULT_HOLDINGS, AUDIT_PATH
        tools.py       tool schemas (TOOLS), execute_tool(), get_returns(), path guard
        prompts.py     SYSTEM_PROMPT, FIRM_PROFILE, build_system_prompt()
        chat.py        run_turn(): tool loop, number check, retry, audit; llm_mode()
        numcheck.py    verify(reply, tool_outputs): every figure must match tool output
        audit.py       append_audit(): one JSON line per turn, API keys redacted
        mock_client.py offline stand-in for the Anthropic client (templated replies)
        cli.py         terminal REPL (`python -m advisor_engine.assistant`)
    ui/app.py          Streamlit demo; lays out engine output, computes nothing
    ui/theme.py        KVS stylesheet + escaped HTML builders (cards, bars, audit panel)
    api/
        settings.py    env config; dev auth forces mock and refuses to run on Render
        auth.py        current_user(): Supabase access token (JWKS/HS256) or X-Dev-User
        store.py       LocalStore: firm-scoped clients, portfolios, drafts, audit
        main.py        FastAPI routes over execute_tool / run_turn / verify
docs/migration-plan.md React + FastAPI + Supabase plan and the decisions behind it
data/sample/           synthetic portfolios, the only committed data
.streamlit/config.toml KVS palette when running `streamlit run` from the repo root
tests/                 one test file per module area
```

## Data flow

```
holdings CSV --load_holdings--> DataFrame(ticker, shares, price, sector, value, weight)
             --get_returns-----> returns DataFrame (columns = tickers, rows = periods)
             --risk_profile----> RiskProfile --to_dict--> JSON tool result
LLM reply --numcheck.verify against all tool results--> shown, retried once, or withheld
every turn --append_audit--> data/audit/audit.jsonl
```

## Key conventions

### Engine (`risk.py`, `holdings.py`, `synthetic.py`)
- Pure functions returning plain floats, lists and dicts (JSON-serialisable). Cast numpy
  scalars with `float()` / `int()` before returning.
- `risk_profile` requires >= 24 return periods and return history for every ticker;
  raise `ValueError` with a clear message for bad input.
- Holdings are long-only: negative shares and non-positive prices are rejected.
- Weights are passed in the same order as `returns.columns` / `holdings["ticker"]`.
- With no `market` series, the equal-weighted universe stands in and `portfolio_beta`
  / `market_share_of_risk` are deliberately removed from the output (they would be
  artifacts). Keep that behaviour unless a real index series is supplied.
- Drawdown and volatility figures carry a `period_label` (default `"monthly"`).
- Docstrings explain the method and its caveats; comments explain *why*. Match that.

### LLM layer (`assistant/`)
- `execute_tool` never raises: errors come back as `ToolResult(..., is_error=True)`.
- Holdings paths must resolve inside `data/`, must be `.csv`, and may not be under
  `data/audit/`. Keep all file access going through `resolve_holdings_path`.
- `get_returns` in `tools.py` is **the one place real market data plugs in**. When it
  changes, update `RETURNS_SOURCE` to match.
- The firm disclaimer is appended verbatim by code in `chat.py`, never given to the
  model and never run through the number check.
- Mode: `ADVISOR_LLM=mock|anthropic`. Unset means mock without `ANTHROPIC_API_KEY`,
  anthropic with one. Model name comes from `ADVISOR_MODEL` (default in `chat.py`).
- The audit log must never contain API keys; `audit._redact` is the safety net, but
  don't put secrets in records in the first place.

### UI (`ui/app.py`)
- Displays engine output only. Any figure shown goes through the same
  `get_risk_profile` tool (so the path rules and audit log apply). Uploads are
  validated and saved to `data/uploads/<random session id>/`; a session lists only
  the samples and its own uploads.
- Styling lives in `ui/theme.py`. Its builders take strings already formatted from
  engine output and HTML-escape them (tickers and sectors can come from uploads). Model
  replies are rendered with plain `st.markdown`, never with `unsafe_allow_html`.
- Mockup sections the engine can't back yet (strategy options, client risk level,
  adviser sign-in, named risk factors) are left out rather than filled with placeholders.

### API (`api/`)
- Routes move engine output around; they compute nothing. Model replies only come from
  `run_turn`, and draft approvals re-run `verify` on the edited text.
- Every store read takes a `firm_id`; another firm's ids answer 404, never 403. Pass the
  firm's directory as `data_dir` to `execute_tool` / `run_turn` so the path guard confines
  the model to that firm, and its audit path (`<firm dir>/audit/`) so logs stay per firm.
- Audit records from the API carry `adviser_id`, `firm_id` and, where relevant,
  `client_id` / `portfolio_id` (via `run_turn(audit_extra=...)`).
- Live model calls require `auth == "supabase"` (`Settings.llm`). Don't add another path to
  the real client.
- Responses never include server file paths (see `_tool_view`).

### Tests
- Tests never hit the network. Assistant tests use a scripted `FakeClient`; UI tests
  use Streamlit's `AppTest` with `ADVISOR_LLM=mock` and a temp `AUDIT_PATH`. API tests use
  `create_app(Settings(auth="dev", store_dir=tmp_path))` and FastAPI's `TestClient`;
  token tests sign HS256 tokens with a test secret.
- Write audit output to `tmp_path` in tests (monkeypatch `audit.AUDIT_PATH` or pass
  `audit_path=`), never to the real `data/audit/`.
- Run `pytest` before committing; the suite is fast (seconds).

## Adding things

### A new engine metric
1. Implement it as a function in `risk.py` (or a new engine module) that returns plain
   numbers/dicts, with a docstring giving the method and its limits.
2. Add it to `RiskProfile` / `risk_profile()` so it appears in `to_dict()`. Add new keys
   alongside existing ones rather than renaming; the prompt, mock client and UI read
   them by name.
3. Test it in `tests/test_risk.py` against a case with a known answer.
4. If the model should explain it, describe the field (in plain-language terms) in
   `prompts.SYSTEM_PROMPT`, and teach `mock_client.py` to mention it if relevant.
5. If it's a new kind of figure (e.g. a count or a value in different units), check
   `numcheck.verify` still matches how the model will quote it; add cases to
   `tests/test_numcheck.py`.

### A new tool for the model
1. Define its schema next to `GET_RISK_PROFILE` in `tools.py` and add it to `TOOLS`.
2. Handle it in `execute_tool`, returning engine output as JSON and errors as
   `ToolResult(is_error=True)`. Route any file paths through `resolve_holdings_path`.
3. Its output is automatically included in what the number check allows; make sure
   every figure the model might quote is actually in that output.
4. Update `mock_client.py` so mock mode can exercise it, and add tests in
   `tests/test_assistant.py` using `FakeClient`.

### Real market data
- Replace the body of `tools.get_returns` (contract: columns cover every holdings
  ticker) and set `RETURNS_SOURCE`. Pass a broad index as `market` to `risk_profile`
  to get meaningful beta / market share of risk.
- Do not commit licensed price or fundamentals data. Everything in `data/` except
  `data/sample/` is gitignored for that reason.

### Prompt or firm-profile changes
- `SYSTEM_PROMPT` rules on numbers are a first line of defence only; the number check
  is the enforcement. Don't loosen `numcheck` tolerances to make a prompt change pass.
- New firm-profile keys go through `build_system_prompt`; anything that must appear
  word-for-word (like a disclaimer) should be added by code, not by the model.

## Versioning

Bump `advisor_engine.__version__` (and `version` in `pyproject.toml`) when engine output
changes, since the audit log records it; tag releases in git (`git tag v0.1.0`).

## Known gaps

- README mentions `cp .env.example .env`, but `.env.example` is not in the repo yet.
  `.env` needs `ANTHROPIC_API_KEY` (and optionally `ADVISOR_LLM`, `ADVISOR_MODEL`).
- `ui/app.py` imports `altair`, which arrives through Streamlit rather than being
  listed in the `ui` extra.
- Number check limits: spelled-out numbers aren't detected, coarse figures can match
  nearby values, and numbers the user typed aren't allowed unless a tool returned them.
- Methodology provenance and data ownership are not yet documented.
