import numpy as np
import pandas as pd
import pytest

from advisor_engine.holdings import validate_holdings
from advisor_engine.risk import (
    effective_number_of_bets,
    max_drawdown,
    risk_profile,
    sector_exposure,
    shrunk_covariance,
)
from advisor_engine.synthetic import synthetic_returns


def _holdings(n=6, sectors=None):
    sectors = sectors or ["A", "A", "B", "B", "C", "C"][:n]
    return validate_holdings(
        pd.DataFrame(
            {
                "ticker": [f"T{i}" for i in range(n)],
                "shares": [100] * n,
                "price": [10.0] * n,
                "sector": sectors,
            }
        )
    )


def test_enb_uncorrelated_equal_weight_is_n():
    n = 5
    cov = np.eye(n) * 0.04
    w = np.ones(n) / n
    enb = effective_number_of_bets(w, cov)["effective_bets"]
    assert enb == pytest.approx(n, rel=1e-6)


def test_enb_perfectly_correlated_is_one():
    n = 5
    cov = np.full((n, n), 0.04)
    w = np.ones(n) / n
    enb = effective_number_of_bets(w, cov)["effective_bets"]
    assert enb == pytest.approx(1.0, abs=1e-6)


def test_enb_concentrated_below_diversified():
    cov = np.eye(4) * 0.04
    diversified = effective_number_of_bets(np.full(4, 0.25), cov)["effective_bets"]
    concentrated = effective_number_of_bets(
        np.array([0.85, 0.05, 0.05, 0.05]), cov
    )["effective_bets"]
    assert concentrated < diversified


def test_shrinkage_in_unit_interval_and_cov_is_psd():
    h = _holdings()
    r = synthetic_returns(list(h["ticker"]), list(h["sector"]), n_periods=60)
    cov, shrink = shrunk_covariance(r)
    assert 0.0 <= shrink <= 1.0
    assert np.all(np.linalg.eigvalsh(cov) > 0)


def test_sector_exposure_sums_to_one_and_sorted():
    h = _holdings()
    exp = sector_exposure(h)
    assert sum(exp.values()) == pytest.approx(1.0)
    vals = list(exp.values())
    assert vals == sorted(vals, reverse=True)


def test_max_drawdown_known_series():
    # +10%, -50%, +20%: peak 1.1, trough 0.55 -> -50%
    r = pd.Series([0.10, -0.50, 0.20])
    assert max_drawdown(r) == pytest.approx(-0.50)


def test_max_drawdown_never_positive():
    r = pd.Series([0.01, 0.02, 0.03])
    assert max_drawdown(r) == 0.0


def test_risk_profile_end_to_end():
    h = _holdings()
    r = synthetic_returns(list(h["ticker"]), list(h["sector"]), n_periods=120)
    p = risk_profile(h, r).to_dict()
    assert 1.0 <= p["concentration"]["effective_bets"] <= len(h)
    assert p["drawdown"]["historical_max_drawdown"] <= 0
    assert p["drawdown"]["stress_loss_1_in_100"] < 0
    assert p["engine_version"]


def test_risk_profile_missing_returns_raises():
    h = _holdings()
    r = synthetic_returns(list(h["ticker"])[:-1], list(h["sector"])[:-1])
    with pytest.raises(ValueError, match="No return history"):
        risk_profile(h, r)


def test_risk_profile_too_short_history_raises():
    h = _holdings()
    r = synthetic_returns(list(h["ticker"]), list(h["sector"]), n_periods=12)
    with pytest.raises(ValueError, match="at least 24"):
        risk_profile(h, r)


def test_negative_shares_rejected():
    df = pd.DataFrame(
        {"ticker": ["A", "B"], "shares": [10, -5], "price": [1.0, 1.0], "sector": ["X", "Y"]}
    )
    with pytest.raises(ValueError, match="short"):
        validate_holdings(df)
