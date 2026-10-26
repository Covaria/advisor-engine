"""Synthetic return generator.

Lets the prototype run end to end without licensed market data. Returns come
from a simple market + sector factor model, so sectors are correlated within
themselves. Replace with real data once licensing is confirmed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_returns(
    tickers: list[str],
    sectors: list[str],
    n_periods: int = 120,
    seed: int = 0,
    market_vol: float = 0.045,
    sector_vol: float = 0.03,
    idio_vol: float = 0.05,
) -> pd.DataFrame:
    """Monthly-style returns: market factor + sector factor + idiosyncratic noise.

    Each row is one period; treat it as monthly, which matches the default
    `period_label` of `risk_profile`. Pass a different label there if the data differs.
    """
    rng = np.random.default_rng(seed)
    unique_sectors = sorted(set(sectors))

    market = rng.normal(0.006, market_vol, n_periods)
    sector_f = {s: rng.normal(0.0, sector_vol, n_periods) for s in unique_sectors}

    cols = {}
    for t, s in zip(tickers, sectors):
        beta = rng.uniform(0.7, 1.3)
        idio = rng.normal(0.0, idio_vol, n_periods)
        cols[t] = beta * market + sector_f[s] + idio
    return pd.DataFrame(cols)
