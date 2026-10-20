# Advisor Analysis Engine (prototype)

Decision-support engine for advisors. The engine computes every number; an LLM
layer (added later) only calls the engine and explains results. It never produces
figures itself.

## Status

Prototype, step 2 of the MVP: **risk profile** from a holdings CSV.

- Effective independent bets (PCA on a Ledoit-Wolf shrunk covariance matrix)
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

## Layout

```
src/advisor_engine/
    holdings.py    load and validate holdings CSV
    synthetic.py   synthetic return generator (no licensed data needed)
    risk.py        the risk profile
    demo.py        end-to-end run on the sample portfolio
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
