"""Load and validate a holdings CSV.

Required columns: ticker, shares, price, sector.
Long-only for the MVP: negative shares are rejected.
"""

from __future__ import annotations

import pandas as pd

REQUIRED = ["ticker", "shares", "price", "sector"]


def load_holdings(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return validate_holdings(df)


def validate_holdings(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Holdings file is missing columns: {missing}")

    df = df[REQUIRED].copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["sector"] = df["sector"].astype(str).str.strip()

    if df["ticker"].duplicated().any():
        dups = sorted(df.loc[df["ticker"].duplicated(), "ticker"].unique())
        raise ValueError(f"Duplicate tickers: {dups}")

    for col in ("shares", "price"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    if (df["shares"] < 0).any():
        raise ValueError("Negative shares found; short positions are out of scope.")
    if (df["price"] <= 0).any():
        raise ValueError("Prices must be positive.")

    df["value"] = df["shares"] * df["price"]
    total = df["value"].sum()
    if total <= 0:
        raise ValueError("Portfolio has zero total value.")
    df["weight"] = df["value"] / total
    return df.reset_index(drop=True)
