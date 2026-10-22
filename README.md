# Advisor Analysis Engine (prototype)

Decision-support engine for advisors. The engine computes every number; an LLM
layer only calls the engine and explains results. It never produces figures
itself.

## Status

Prototype, step 2 of the MVP: **risk profile** from a holdings CSV.

- Effective independent bets (PCA on a Ledoit-Wolf shrunk covariance matrix)
- Market-adjusted concentration: portfolio beta, share of risk from the market,
  and effective bets on the residuals (equal-weighted universe stand-in until a
  broad index series is supplied via `market`)
- Sector-level effective bets
- Sector exposure
- Drawdown sensitivity (historical and covariance-based stress)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m advisor_engine.demo
```

## Assistant (LLM layer)

```bash
pip install -e ".[dev,llm]"
cp .env.example .env             # then set ANTHROPIC_API_KEY
python -m advisor_engine.assistant                      # sample portfolio
python -m advisor_engine.assistant --holdings data/my_book.csv   # must be inside data/
```

Type questions at the prompt; `/quit` exits. The model name comes from
`ADVISOR_MODEL` (default `claude-sonnet-5-5`).

### Number-check guardrail

The model gets one tool, `get_risk_profile`, and is told never to compute or invent
a figure. It is not trusted to obey: after it answers, `assistant/numcheck.py`
extracts every number in the reply and checks it against all tool output in the
conversation. A figure matches if it equals a tool value rounded to the precision the
reply used (21.1% matches 0.2113). If anything doesn't match, the model gets one
automatic retry; if it still fails, the reply is withheld and the unmatched figures
are listed.

Limits: spelled-out numbers ("twelve") are not detected; rounding to the reply's
precision means a coarse figure ("5") can match a nearby tool value; figures the
user typed in their own question are not allowed unless a tool also returned them.

### Audit log

Every turn appends one JSON line to `data/audit/audit.jsonl`: timestamp, engine
version, model, SHA-256 of the holdings file, tool calls and outputs, the model's
reply, the verification result, and whether the reply was blocked. API keys are never
written. `data/` is gitignored, so the log stays local.

### Firm profile

`prompts.FIRM_PROFILE` (default `None`) takes `objective`, `tone` and `disclaimer`.
Objective and tone go into the system prompt. The disclaimer is appended verbatim to
verified replies by code, so the model never rewrites it. The wording is yours to
supply; none is built in.

## Layout

```
src/advisor_engine/
    holdings.py    load and validate holdings CSV
    synthetic.py   synthetic return generator (no licensed data needed)
    risk.py        the risk profile
    demo.py        end-to-end run on the sample portfolio
    assistant/     LLM layer: tools, prompts, numcheck, audit, chat loop, CLI
data/sample/       small synthetic portfolios, safe to commit
tests/
```

## Data and ownership

- Everything under `data/` except `data/sample/` is gitignored. Do not commit
  licensed price or fundamentals data until commercial-use licensing is confirmed.
- Methodology provenance and ownership are not yet written down.

## Versioning

`advisor_engine.__version__` is the engine version the audit log will record.
Tag releases in git (`git tag v0.1.0`) when it changes.
