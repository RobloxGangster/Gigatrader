from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import ta_helpers as ta

FEATURE_LIST = [
    # Returns / Vol
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "ret_15",
    "ret_30",
    "roll_vol_10",
    "roll_vol_30",
    "cum_dd_100",
    "kurt_30",
    "skew_30",
    "realized_vol_30",
    "realized_quarticity_30",
    # Trend
    "ema_12",
    "ema_26",
    "ema_diff",
    "macd",
    "macd_signal",
    "macd_hist",
    "mom_10",
    "adx_14",
    "di_pos",
    "di_neg",
    "trend_strength_20",
    # Reversion / Bands
    "rsi_2",
    "rsi_14",
    "bb_mid_20",
    "bb_upper_20",
    "bb_lower_20",
    "bb_pos_20",
    "bb_width_20",
    "zclose_20",
    "stoch_k_14",
    "stoch_d_14",
    # Volatility / Range
    "tr",
    "atr_14",
    "atr_norm_14",
    "donchian_high_20",
    "donchian_low_20",
    "dist_to_h20",
    "dist_to_l20",
    # Volume / Liquidity
    "vol_sma_20",
    "vol_ratio_5",
    "vol_ratio_20",
    "obv",
    "obv_slope_10",
    "dollar_vol_20",
    # VWAP / Microstructure
    "session_vwap",
    "vwap_dev",
    "spread_bps",
    "depth_imbalance",
    "microprice",
    "microprice_dev",
    # Time / Seasonality
    "minute_of_day",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "is_opening15",
    "is_powerhour",
    # Gaps / Candles
    "gap_overnight",
    "body",
    "range",
    "body_norm",
    "wick_up",
    "wick_down",
    "doji_score",
    "hammer_score",
    # Cross Asset
    "spy_corr_30",
]


def _safe_pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
    return series.pct_change(periods=periods).replace([np.inf, -np.inf], np.nan)


def _forward_fill(df: pd.DataFrame) -> pd.DataFrame:
    return df.ffill()


def _load_spy_reference(df: pd.DataFrame) -> pd.Series | None:
    spy_path = Path("fixtures") / "bars_SPY.csv"
    if not spy_path.exists():
        return None
    spy_df = pd.read_csv(spy_path)
    spy_df["time"] = pd.to_datetime(spy_df["time"])
    left = df[["time"]].merge(spy_df[["time", "close"]], on="time", how="left")
    return left["close"].fillna(method="ffill")


def build_features(
    df: pd.DataFrame,
    quote_df: pd.DataFrame | None = None,
    session_open: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if df.empty:
        raise ValueError("Dataframe must not be empty")

    work = df.copy()
    work["time"] = pd.to_datetime(work["time"])
    work = work.sort_values("time").reset_index(drop=True)
    work[["open", "high", "low", "close", "volume"]] = work[[
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]].astype(float)

    returns = {
        f"ret_{p}": _safe_pct_change(work["close"], p)
        for p in (1, 3, 5, 10, 15, 30)
    }

    roll_vol_10 = work["close"].pct_change().rolling(10, min_periods=10).std()
    roll_vol_30 = work["close"].pct_change().rolling(30, min_periods=30).std()

    rolling_max = work["close"].rolling(100, min_periods=100).max()
    drawdown = work["close"] / (rolling_max + 1e-9) - 1
    cum_dd_100 = drawdown.rolling(100, min_periods=100).min()

    kurt_30 = ta.rolling_kurt(work["close"].pct_change(), 30)
    skew_30 = ta.rolling_skew(work["close"].pct_change(), 30)
    realized_vol_30 = ta.realized_vol(work["close"], 30)
    realized_quarticity_30 = ta.realized_quarticity(work["close"], 30)

    ema_12 = ta.ema(work["close"], 12)
    ema_26 = ta.ema(work["close"], 26)
    ema_diff = ema_12 - ema_26
    macd_line, macd_signal, macd_hist = ta.macd(work["close"])
    mom_10 = work["close"].diff(10)
    adx_14, di_pos, di_neg = ta.adx(work["high"], work["low"], work["close"], 14)
    atr_14 = ta.atr(work["high"], work["low"], work["close"], 14)
    trend_strength_20 = (ema_diff.abs() / (atr_14 + 1e-9)).clip(upper=10)

    rsi_2 = ta.rsi(work["close"], 2)
    rsi_14 = ta.rsi(work["close"], 14)
    bb_mid, bb_upper, bb_lower = ta.bollinger(work["close"], 20, 2)
    bb_pos = (work["close"] - bb_lower) / (bb_upper - bb_lower + 1e-9)
    bb_width = (bb_upper - bb_lower) / (work["close"] + 1e-9)
    zclose = ta.zscore(work["close"], 20).clip(-10, 10)
    stoch_k, stoch_d = ta.stochastic(work["high"], work["low"], work["close"])

    prev_close = work["close"].shift(1)
    tr = (work[["high", "low", "close"]].max(axis=1) - work[["high", "low", "close"]].min(axis=1)).fillna(0)
    donchian_high, donchian_low = ta.donchian(work["high"], work["low"], 20)
    dist_to_h20 = (work["close"] - donchian_high) / (donchian_high + 1e-9)
    dist_to_l20 = (work["close"] - donchian_low) / (donchian_low + 1e-9)
    atr_norm = atr_14 / (work["close"] + 1e-9)

    vol_sma_20 = work["volume"].rolling(20, min_periods=20).mean()
    vol_ratio_5 = work["volume"] / (work["volume"].rolling(5, min_periods=5).mean() + 1e-9)
    vol_ratio_20 = work["volume"] / (vol_sma_20 + 1e-9)
    obv = ta.obv(work["close"], work["volume"])
    obv_slope_10 = obv.diff(10)
    dollar_vol_20 = (work["close"] * work["volume"]).rolling(20, min_periods=20).mean()

    session_vwap = ta.anchored_vwap(work)
    vwap_dev = (work["close"] - session_vwap) / (session_vwap + 1e-9)

    spread_bps = pd.Series(0.0, index=work.index)
    depth_imbalance = pd.Series(0.0, index=work.index)
    microprice = work["close"].copy()
    microprice_dev = pd.Series(0.0, index=work.index)
    if quote_df is not None and not quote_df.empty:
        q = quote_df.copy()
        q["time"] = pd.to_datetime(q["time"])
        merged = pd.merge_asof(work[["time", "close"]], q.sort_values("time"), on="time", direction="backward")
        bid = merged["bid"].fillna(merged["close"]) \
            .replace([np.inf, -np.inf], np.nan)
        ask = merged["ask"].fillna(merged["close"]) \
            .replace([np.inf, -np.inf], np.nan)
        spread = (ask - bid).abs()
        spread_bps = (spread / (merged["close"] + 1e-9)) * 1e4
        depth_imbalance = (merged.get("bidsize", 0) - merged.get("asksize", 0)) / (
            (merged.get("bidsize", 0) + merged.get("asksize", 0) + 1e-9)
        )
        microprice = (ask * merged.get("bidsize", 1) + bid * merged.get("asksize", 1)) / (
            (merged.get("bidsize", 1) + merged.get("asksize", 1) + 1e-9)
        )
        microprice_dev = (microprice - merged["close"]) / (merged["close"] + 1e-9)

    minute_of_day = work["time"].dt.hour * 60 + work["time"].dt.minute
    hour_angle = 2 * np.pi * work["time"].dt.hour / 24
    hour_sin = np.sin(hour_angle)
    hour_cos = np.cos(hour_angle)
    dow_angle = 2 * np.pi * work["time"].dt.dayofweek / 7
    dow_sin = np.sin(dow_angle)
    dow_cos = np.cos(dow_angle)
    is_opening15 = ((minute_of_day - minute_of_day.min()) < 15).astype(float)
    is_powerhour = ((work["time"].dt.hour == 15) & (work["time"].dt.minute >= 0)).astype(float)

    prev_session_close = prev_close.fillna(method="ffill")
    gap_overnight = (work["open"] - prev_session_close) / (prev_session_close + 1e-9)
    candle_range = (work["high"] - work["low"]).replace(0, np.nan)
    body = (work["close"] - work["open"])
    body_norm = body / (candle_range + 1e-9)
    wick_up = (work["high"] - work[["close", "open"]].max(axis=1)) / (candle_range + 1e-9)
    wick_down = (work[["close", "open"]].min(axis=1) - work["low"]) / (candle_range + 1e-9)
    doji_score = (1 - body.abs() / (candle_range + 1e-9)).clip(lower=0)
    hammer_score = (wick_down - wick_up).clip(lower=0)

    spy_series = _load_spy_reference(work)
    if spy_series is not None:
        spy_ret = spy_series.pct_change()
        asset_ret = work["close"].pct_change()
        spy_corr_30 = asset_ret.rolling(30, min_periods=30).corr(spy_ret)
    else:
        spy_corr_30 = pd.Series(0.0, index=work.index)

    feature_df = pd.DataFrame({
        **returns,
        "roll_vol_10": roll_vol_10,
        "roll_vol_30": roll_vol_30,
        "cum_dd_100": cum_dd_100,
        "kurt_30": kurt_30,
        "skew_30": skew_30,
        "realized_vol_30": realized_vol_30,
        "realized_quarticity_30": realized_quarticity_30,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "ema_diff": ema_diff,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "mom_10": mom_10,
        "adx_14": adx_14,
        "di_pos": di_pos,
        "di_neg": di_neg,
        "trend_strength_20": trend_strength_20,
        "rsi_2": rsi_2,
        "rsi_14": rsi_14,
        "bb_mid_20": bb_mid,
        "bb_upper_20": bb_upper,
        "bb_lower_20": bb_lower,
        "bb_pos_20": bb_pos,
        "bb_width_20": bb_width,
        "zclose_20": zclose,
        "stoch_k_14": stoch_k,
        "stoch_d_14": stoch_d,
        "tr": tr,
        "atr_14": atr_14,
        "atr_norm_14": atr_norm,
        "donchian_high_20": donchian_high,
        "donchian_low_20": donchian_low,
        "dist_to_h20": dist_to_h20,
        "dist_to_l20": dist_to_l20,
        "vol_sma_20": vol_sma_20,
        "vol_ratio_5": vol_ratio_5,
        "vol_ratio_20": vol_ratio_20,
        "obv": obv,
        "obv_slope_10": obv_slope_10,
        "dollar_vol_20": dollar_vol_20,
        "session_vwap": session_vwap,
        "vwap_dev": vwap_dev,
        "spread_bps": spread_bps,
        "depth_imbalance": depth_imbalance,
        "microprice": microprice,
        "microprice_dev": microprice_dev,
        "minute_of_day": minute_of_day,
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "dow_sin": dow_sin,
        "dow_cos": dow_cos,
        "is_opening15": is_opening15,
        "is_powerhour": is_powerhour,
        "gap_overnight": gap_overnight,
        "body": body,
        "range": candle_range,
        "body_norm": body_norm,
        "wick_up": wick_up,
        "wick_down": wick_down,
        "doji_score": doji_score,
        "hammer_score": hammer_score,
        "spy_corr_30": spy_corr_30,
    })

    feature_df = _forward_fill(feature_df)
    feature_df = feature_df.dropna().reset_index(drop=True)
    feature_df = feature_df.replace([np.inf, -np.inf], np.nan).dropna()

    feature_df = feature_df[FEATURE_LIST]
    meta = {
        "generated_at": datetime.utcnow().isoformat(),
        "rows": len(feature_df),
    }
    return feature_df, meta
