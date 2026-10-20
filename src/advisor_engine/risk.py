"""Risk profile: concentration, sector exposure, drawdown sensitivity.

Every function returns plain numbers or small dicts. The LLM layer will call
`risk_profile` and explain the output; it never computes figures itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from . import __version__


def shrunk_covariance(returns: pd.DataFrame) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf shrunk covariance. Returns (covariance, shrinkage intensity)."""
    # Shrinking toward a structured target stabilises the estimate when the
    # number of periods is small relative to the number of holdings.
    lw = LedoitWolf().fit(returns.values)
    return lw.covariance_, float(lw.shrinkage_)


def effective_number_of_bets(weights: np.ndarray, cov: np.ndarray) -> dict:
    """Effective independent bets via PCA (Meucci's entropy measure).

    Decompose the covariance into principal components. The portfolio's
    exposure to component i is e_i' w, and its variance contribution is
    (e_i' w)^2 * lambda_i. Normalise to p_i and take exp(entropy(p)).
    A value near 1 means one dominant bet; near N means N independent bets.
    """
    eigvals, eigvecs = np.linalg.eigh(cov)
    # eigh returns ascending eigenvalues; sort so component 0 is the largest.
    order = np.argsort(eigvals)[::-1]
    eigvals, eigvecs = eigvals[order], eigvecs[:, order]

    # Project weights onto the principal components, then weight each squared
    # exposure by its eigenvalue to get that component's share of variance.
    exposures = eigvecs.T @ weights
    contrib = (exposures**2) * eigvals
    p = contrib / contrib.sum()
    # Drop ~zero shares so log(0) doesn't produce NaN in the entropy.
    p_pos = p[p > 1e-12]
    enb = float(np.exp(-np.sum(p_pos * np.log(p_pos))))

    return {
        "effective_bets": enb,
        "n_positions": int(len(weights)),
        "top_component_share": float(p[0]),
        "component_shares": [float(x) for x in p[:5]],
    }


def position_risk(holdings: pd.DataFrame, cov: np.ndarray, corr_floor: float = 1e-12) -> list[dict]:
    """Per-position facts that back a "why is this position here / why does it matter".

    - risk_share: fraction of portfolio variance contributed by the position
      (w_i * (Cov w)_i / port_var). Sums to 1.
    - risk_to_weight: risk_share / weight. Above 1 means the position adds more
      risk than its size suggests.
    - avg_corr_to_rest: weighted average correlation with the other holdings.
    """
    w = holdings["weight"].to_numpy()
    port_var = float(w @ cov @ w)
    risk_share = w * (cov @ w) / port_var

    # Convert covariance to correlation: corr_ij = cov_ij / (vol_i * vol_j).
    vol = np.sqrt(np.diag(cov))
    corr = cov / np.outer(vol, vol)
    out = []
    for i, row in holdings.iterrows():
        # Mask out the position itself; its self-correlation of 1 would bias the average.
        others = np.arange(len(w)) != i
        wo = w[others]
        # corr_floor guards against dividing by zero when there are no other holdings.
        avg_corr = float(np.sum(wo * corr[i, others]) / max(wo.sum(), corr_floor))
        out.append(
            {
                "ticker": row["ticker"],
                "sector": row["sector"],
                "weight": float(w[i]),
                "risk_share": float(risk_share[i]),
                "risk_to_weight": float(risk_share[i] / w[i]) if w[i] > 0 else 0.0,
                "volatility": float(vol[i]),
                "avg_corr_to_rest": avg_corr,
            }
        )
    # Biggest risk contributors first, so callers can slice the top N.
    return sorted(out, key=lambda d: d["risk_share"], reverse=True)


def sector_exposure(holdings: pd.DataFrame) -> dict[str, float]:
    """Portfolio weight by sector, largest first."""
    s = holdings.groupby("sector")["weight"].sum().sort_values(ascending=False)
    return {k: float(v) for k, v in s.items()}


def max_drawdown(portfolio_returns: pd.Series) -> float:
    """Worst peak-to-trough loss of the compounded return series (negative number)."""
    # Growth of 1 unit, tracked against its running high-water mark.
    wealth = (1.0 + portfolio_returns).cumprod()
    peak = wealth.cummax()
    return float((wealth / peak - 1.0).min())


def drawdown_sensitivity(
    weights: np.ndarray,
    cov: np.ndarray,
    portfolio_returns: pd.Series,
    z: float = 2.33,
) -> dict:
    """Two views of downside.

    - historical_max_drawdown: worst drawdown in the supplied return history.
    - stress_loss_1_in_100: parametric one-period loss at ~99% confidence
      using the shrunk covariance (z=2.33), ignoring the mean.
    """
    # Portfolio volatility: sqrt(w' Cov w), in the same period units as the returns.
    port_vol = float(np.sqrt(weights @ cov @ weights))
    return {
        "historical_max_drawdown": max_drawdown(portfolio_returns),
        "period_volatility": port_vol,
        "stress_loss_1_in_100": -z * port_vol,
    }


@dataclass
class RiskProfile:
    engine_version: str
    n_periods: int
    shrinkage: float
    concentration: dict
    sector_exposure: dict
    drawdown: dict
    largest_positions: list = field(default_factory=list)
    positions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def risk_profile(holdings: pd.DataFrame, returns: pd.DataFrame) -> RiskProfile:
    """Build the risk profile for a validated holdings frame and a returns frame.

    `returns` columns must cover every holdings ticker.
    """
    tickers = list(holdings["ticker"])
    missing = [t for t in tickers if t not in returns.columns]
    if missing:
        raise ValueError(f"No return history for: {missing}")

    # Keep only periods where every holding has a return, so the covariance
    # and the portfolio return series are built on the same sample.
    r = returns[tickers].dropna()
    # Too few observations makes the covariance estimate unreliable.
    if len(r) < 24:
        raise ValueError("Need at least 24 periods of returns.")

    weights = holdings["weight"].to_numpy()
    cov, shrink = shrunk_covariance(r)

    # Period-by-period portfolio return assuming constant weights.
    port_ret = pd.Series(r.to_numpy() @ weights, index=r.index)

    top =holdings.nlargest(5, "weight")[["ticker", "weight", "sector"]]
    return RiskProfile(
        engine_version=__version__,
        n_periods=int(len(r)),
        shrinkage=shrink,
        concentration=effective_number_of_bets(weights, cov),
        sector_exposure=sector_exposure(holdings),
        drawdown=drawdown_sensitivity(weights, cov, port_ret),
        largest_positions=top.to_dict("records"),
        positions=position_risk(holdings, cov),
    )