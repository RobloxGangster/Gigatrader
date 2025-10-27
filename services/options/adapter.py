"""Option chain adapter with validation.

This module abstracts how option chains are retrieved so that strategies can
operate on a normalized DataFrame. When running in ``MOCK_MODE`` it loads
pre-recorded chains stored under ``artifacts/options_mock``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import MOCK_MODE
from core.runtime_flags import get_runtime_flags

MIN_OPEN_INTEREST = 25
"""Minimum open interest required for a contract to be considered liquid."""

MAX_SPREAD_BPS = 1500
"""Maximum bid/ask spread expressed in basis points relative to the mid."""

_ALLOWED_EXPIRY_WEEKDAY = 4  # Friday


def _artifacts_dir() -> Path:
    base = Path(os.getenv("ARTIFACTS_DIR", "artifacts"))
    override = os.getenv("OPTIONS_MOCK_DIR")
    return Path(override) if override else base / "options_mock"


def _load_mock_chain(symbol: str, as_of: pd.Timestamp) -> pd.DataFrame:
    directory = _artifacts_dir()
    stem = f"{symbol.upper()}_{as_of.strftime('%Y-%m-%d')}"

    parquet_path = directory / f"{stem}.parquet"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)

    json_path = directory / f"{stem}.json"
    if json_path.exists():
        df = pd.read_json(json_path, orient="records", convert_dates=False)
        underlying = df.get("underlying_price")
        if underlying is None:
            underlying = pd.Series(pd.NA, index=df.index)

        # Normalise types to mirror the parquet representation.
        return df.assign(
            as_of=pd.to_datetime(df["as_of"]),
            expiry=pd.to_datetime(df["expiry"]),
            strike=df["strike"].astype(float),
            iv=df["iv"].astype(float),
            bid=df["bid"].astype(float),
            ask=df["ask"].astype(float),
            oi=df["oi"].astype(int),
            underlying_price=pd.to_numeric(underlying, errors="coerce"),
        )

    raise FileNotFoundError(
        "Mock option chain not found for "
        f"{symbol} @ {as_of.date()}: {parquet_path} or {json_path}"
    )


def _filter_liquidity(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    filtered = filtered.dropna(subset=["bid", "ask", "oi", "expiry"])
    filtered["expiry"] = pd.to_datetime(filtered["expiry"], utc=False)
    filtered = filtered[filtered["expiry"].dt.dayofweek == _ALLOWED_EXPIRY_WEEKDAY]
    filtered = filtered[filtered["oi"] >= MIN_OPEN_INTEREST]

    # Ensure positive bid/ask and compute mid for spread calculations.
    filtered = filtered[(filtered["bid"] > 0) & (filtered["ask"] > 0)]
    filtered = filtered[filtered["ask"] >= filtered["bid"]]

    mid = (filtered["bid"] + filtered["ask"]) / 2
    filtered = filtered.assign(mid=mid)
    filtered = filtered[filtered["mid"] > 0]

    spread = filtered["ask"] - filtered["bid"]
    spread_bps = (spread / filtered["mid"]) * 10_000
    filtered = filtered[spread_bps <= MAX_SPREAD_BPS]

    filtered = filtered.sort_values(["expiry", "strike", "side"]).reset_index(drop=True)
    return filtered


def _mock_mode_enabled() -> bool:
    try:
        return bool(get_runtime_flags().mock_mode)
    except Exception:
        env = os.getenv("MOCK_MODE")
        if env is not None:
            return env.lower() in ("1", "true", "yes", "on")
    return bool(MOCK_MODE)


def get_option_chain(symbol: str, as_of: Any) -> pd.DataFrame:
    """Return a normalized option chain for ``symbol`` as of ``as_of``.

    Parameters
    ----------
    symbol:
        Underlying ticker symbol.
    as_of:
        Timestamp or string representing the observation time.

    Returns
    -------
    pandas.DataFrame
        A DataFrame containing the filtered contracts with greeks and
        liquidity columns. The frame always contains a ``mid`` column for
        downstream consumers.
    """

    as_of_ts = pd.to_datetime(as_of)

    if _mock_mode_enabled():
        raw = _load_mock_chain(symbol, as_of_ts)
    else:
        raise NotImplementedError("Live option chain retrieval is not implemented")

    return _filter_liquidity(raw)
