"""Expected move calculations for option chains."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def expected_move(chain: pd.DataFrame, as_of: Any) -> float:
    """Estimate the expected move using the ATM implied volatility.

    The computation uses the nearest expiry after ``as_of`` and averages the
    implied volatility of contracts with strikes closest to the underlying
    price. The expected move is calculated as ``S * IV * sqrt(T)`` where ``T``
    is the time to expiry expressed in years.
    """

    if chain.empty:
        raise ValueError("Option chain is empty")

    as_of_ts = pd.to_datetime(as_of)
    df = chain.copy()
    df["expiry"] = pd.to_datetime(df["expiry"], utc=False)
    df = df[df["expiry"] > as_of_ts]
    if df.empty:
        raise ValueError("No expiries after the as_of timestamp")

    expiry = df["expiry"].min()
    window = df[df["expiry"] == expiry]

    if "underlying_price" not in window.columns:
        raise ValueError("Chain is missing underlying_price information")

    underlying_price = float(window["underlying_price"].iloc[0])

    window = window.assign(distance=(window["strike"] - underlying_price).abs())
    min_distance = window["distance"].min()
    atm = window[window["distance"] == min_distance]

    if atm.empty or atm["iv"].isna().all():
        raise ValueError("Unable to determine ATM implied volatility")

    atm_iv = float(atm["iv"].mean())
    time_fraction = (expiry - as_of_ts) / pd.Timedelta(days=365)
    time_years = float(time_fraction)
    if time_years <= 0:
        raise ValueError("Time to expiry must be positive")

    return underlying_price * atm_iv * math.sqrt(time_years)
