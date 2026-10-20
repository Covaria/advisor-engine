"""End-to-end demo on the sample portfolio with synthetic returns."""

import json
from pathlib import Path

from .holdings import load_holdings
from .risk import risk_profile
from .synthetic import synthetic_returns

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample" / "sample_holdings.csv"


def main() -> None:
    holdings = load_holdings(str(SAMPLE))
    returns = synthetic_returns(list(holdings["ticker"]), list(holdings["sector"]))
    profile = risk_profile(holdings, returns)
    print(json.dumps(profile.to_dict(), indent=2))


if __name__ == "__main__":
    main()
