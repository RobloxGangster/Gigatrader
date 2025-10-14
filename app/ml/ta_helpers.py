from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-9


def _to_series(values: pd.Series | pd.DataFrame | np.ndarray) -> pd.Series:
    if isinstance(values, pd.Series):
        return values
    if isinstance(values, pd.DataFrame):
        return values.iloc[:, 0]
    return pd.Series(values)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    diff = series.diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / (avg_loss + EPS)
    return 100 - (100 / (1 + rs))


def bollinger(series: pd.Series, period: int = 20, std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(period, min_periods=period).mean()
    dev = series.rolling(period, min_periods=period).std(ddof=0)
    upper = mid + std * dev
    lower = mid - std * dev
    return mid, upper, lower


def anchored_vwap(df: pd.DataFrame, price_col: str = "close", volume_col: str = "volume") -> pd.Series:
    price = df[price_col]
    volume = df[volume_col]
    cum_vol = volume.cumsum().replace(0, np.nan)
    cum_pv = (price * volume).cumsum()
    return cum_pv / (cum_vol + EPS)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def donchian(high: pd.Series, low: pd.Series, period: int = 20) -> tuple[pd.Series, pd.Series]:
    return (
        high.rolling(period, min_periods=period).max(),
        low.rolling(period, min_periods=period).min(),
    )


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = atr(high, low, close, period).fillna(0)
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False).mean() / (tr + EPS)
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False).mean() / (tr + EPS)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + EPS) * 100
    adx_series = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx_series, plus_di, minus_di


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().fillna(0).apply(np.sign)
    return (direction * volume).cumsum()


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(period, min_periods=period).min()
    highest_high = high.rolling(period, min_periods=period).max()
    k = (close - lowest_low) / (highest_high - lowest_low + EPS)
    k = k.rolling(smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(smooth_d, min_periods=smooth_d).mean()
    return 100 * k, 100 * d


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    typical = (high + low + close) / 3
    sma = typical.rolling(period, min_periods=period).mean()
    mad = (typical - sma).abs().rolling(period, min_periods=period).mean()
    return (typical - sma) / (0.015 * (mad + EPS))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal = ema(macd_line, signal_period)
    hist = macd_line - signal
    return macd_line, signal, hist


def zscore(series: pd.Series, period: int = 20) -> pd.Series:
    mean = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std(ddof=0)
    return (series - mean) / (std + EPS)


def rolling_skew(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).skew()


def rolling_kurt(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).kurt()


def entropy(series: pd.Series, bins: int = 20) -> pd.Series:
    def _entropy(window: pd.Series) -> float:
        hist, _ = np.histogram(window.dropna(), bins=bins, density=True)
        hist = hist + EPS
        prob = hist / hist.sum()
        return -np.sum(prob * np.log(prob))

    return series.rolling(bins, min_periods=bins).apply(_entropy, raw=False)


def realized_vol(series: pd.Series, period: int = 30) -> pd.Series:
    returns = series.pct_change().fillna(0)
    realized = (returns ** 2).rolling(period, min_periods=period).sum()
    return np.sqrt(realized.clip(lower=0))


def realized_quarticity(series: pd.Series, period: int = 30) -> pd.Series:
    returns = series.pct_change().fillna(0)
    quart = (returns ** 4).rolling(period, min_periods=period).sum()
    return quart
