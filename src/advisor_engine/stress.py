"""Stress scenarios: an instant shock per sector, applied to the portfolio's weights.

Method: each holding's value moves by its sector's shock (or the scenario default for
sectors it doesn't name). The portfolio's move is the weight-sum of those shocks, so
the result is exact for the stated shocks: there is no model or history behind it.

Limits, which the result carries in `basis`:
- The presets are illustrative shapes (a broad fall, a sector sell-off, rising rates,
  a recession), not calibrated to any historical episode. Review them before using the
  figures with clients.
- Every holding in a sector moves by the same amount; stock-specific moves, gaps and
  correlations between sectors beyond the stated shocks are ignored.
"""

from __future__ import annotations

import pandas as pd

BASIS = "Illustrative preset shocks per sector, not calibrated to a historical period."

SCENARIOS: dict[str, dict] = {
    "broad_selloff": {
        "label": "Broad market sell-off",
        "description": "Every holding falls 20%.",
        "default": -0.20,
        "sectors": {},
    },
    "tech_selloff": {
        "label": "Technology sell-off",
        "description": "Technology falls 30% and Communication Services 20%; other sectors fall 5%.",
        "default": -0.05,
        "sectors": {"Technology": -0.30, "Communication Services": -0.20},
    },
    "rising_rates": {
        "label": "Rising rates",
        "description": "Rate-sensitive sectors fall most: Real Estate and Utilities 15%, "
                       "Technology 12%; Financials fall 2%; other sectors fall 6%.",
        "default": -0.06,
        "sectors": {"Real Estate": -0.15, "Utilities": -0.15, "Technology": -0.12,
                    "Financials": -0.02},
    },
    "recession": {
        "label": "Recession",
        "description": "Cyclical sectors fall 25%; defensive sectors (Consumer Staples, "
                       "Health Care, Utilities) fall 8%; other sectors fall 15%.",
        "default": -0.15,
        "sectors": {"Consumer Discretionary": -0.25, "Industrials": -0.25, "Energy": -0.25,
                    "Financials": -0.25, "Materials": -0.25, "Consumer Staples": -0.08,
                    "Health Care": -0.08, "Utilities": -0.08},
    },
}


def scenario_list() -> list[dict]:
    """The presets as data, for the API and UI to show what each one assumes."""
    return [{"id": k, **v} for k, v in SCENARIOS.items()]


def stress_test(holdings: pd.DataFrame, sector_shocks: dict[str, float],
                default_shock: float) -> dict:
    """Apply `sector_shocks` (fractions, e.g. -0.3) to a validated holdings frame.

    Returns the portfolio's return and value change, plus the same per sector and per
    position (largest loss first). Shocks must be between -100% and +100%.
    """
    shocks = {str(k): float(v) for k, v in sector_shocks.items()}
    for v in [*shocks.values(), default_shock]:
        if not -1.0 <= v <= 1.0:
            raise ValueError("Shocks must be between -100% and +100%.")

    h = holdings.copy()
    h["shock"] = h["sector"].map(shocks).fillna(float(default_shock))
    h["contribution"] = h["weight"] * h["shock"]  # share of the portfolio's move
    h["value_change"] = h["value"] * h["shock"]

    by_sector = h.groupby("sector").agg(weight=("weight", "sum"), shock=("shock", "first"),
                                        contribution=("contribution", "sum"))
    by_sector = by_sector.sort_values("contribution")
    positions = h.sort_values("contribution")[
        ["ticker", "sector", "weight", "shock", "contribution", "value_change"]]
    return {
        "portfolio_return": float(h["contribution"].sum()),
        "portfolio_value": float(h["value"].sum()),
        "value_change": float(h["value_change"].sum()),
        "default_shock": float(default_shock),
        "sectors": [{"sector": s, **{k: float(v) for k, v in row.items()}}
                    for s, row in by_sector.iterrows()],
        "positions": [{k: (float(v) if k not in ("ticker", "sector") else v)
                       for k, v in row.items()} for row in positions.to_dict("records")],
        "basis": BASIS,
    }


def run_scenario(holdings: pd.DataFrame, scenario_id: str) -> dict:
    if scenario_id not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    sc = SCENARIOS[scenario_id]
    return {"scenario": {"id": scenario_id, **sc},
            **stress_test(holdings, sc["sectors"], sc["default"])}
