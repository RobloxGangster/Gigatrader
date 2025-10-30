from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.data.market import IMarketDataClient, bars_to_df
from app.utils.cache import TTLCache
from app.ml.features import build_features
from backend.utils.structlog import jlog

logger = logging.getLogger(__name__)


class SignalConfig(BaseModel):
    lookback: int = 400
    tf_intraday: str = "1Min"
    tf_swing: str = "1Day"
    universe: list[str] = ["SPY", "AAPL", "MSFT", "NVDA"]
    option_delta: tuple[float, float] = (0.2, 0.4)
    min_option_oi: int = 50
    top_n: int = 10
    min_dollar_vol: float = 5e6
    max_spread_bps: int = 15
    min_session_bars: int = 60
    enable_revert: bool = True
    enable_momo: bool = True
    enable_swing: bool = True
    enable_options: bool = True


class SignalCandidate(BaseModel):
    kind: Literal["equity", "option"]
    symbol: str
    side: Literal["buy", "sell"]
    entry: float
    stop: float | None = None
    target: float | None = None
    confidence: float = Field(ge=0, le=2)
    rationale: str
    meta: dict = Field(default_factory=dict)


class SignalBundle(BaseModel):
    generated_at: datetime
    profile: str
    candidates: list[SignalCandidate]


class SignalEngine:
    def __init__(self, client: IMarketDataClient, config: SignalConfig | None = None) -> None:
        self.client = client
        self.config = config or SignalConfig()
        self.cache = TTLCache(ttl_seconds=3.0)

    def _fetch_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        cache_key = (symbol, timeframe, limit)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        bars = self.client.get_bars(symbol, timeframe=timeframe, limit=limit)
        df = bars_to_df(bars)
        self.cache.set(cache_key, df)
        return df

    def _fetch_quote(self, symbol: str) -> dict:
        cache_key = ("quote", symbol)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            quote = self.client.get_quote(symbol)
        except Exception:  # pragma: no cover - defensive
            quote = {}
        self.cache.set(cache_key, quote)
        return quote

    def _liquidity_pass(self, feature_row: pd.Series, quote: dict) -> bool:
        dollar_vol = float(feature_row.get("dollar_vol_20", 0))
        if dollar_vol < self.config.min_dollar_vol:
            return False
        spread = None
        if quote:
            bid = quote.get("bid")
            ask = quote.get("ask")
            last = quote.get("last") or quote.get("mid", 0)
            if bid and ask:
                spread = abs(float(ask) - float(bid)) / (float(last or (bid + ask) / 2) + 1e-9) * 1e4
        if spread is None:
            spread = float(feature_row.get("spread_bps", 0))
        return spread <= self.config.max_spread_bps if spread else True

    def _intraday_momentum(self, symbol: str, df: pd.DataFrame, feature_row: pd.Series, quote: dict) -> SignalCandidate | None:
        row = feature_row
        if not self._liquidity_pass(row, quote):
            return None

        price = float(df["close"].iloc[-1])
        session_high = float(df["high"].cummax().iloc[-2]) if len(df) > 1 else price
        session_low = float(df["low"].cummin().iloc[-2]) if len(df) > 1 else price
        breakout_up = price > session_high
        breakout_down = price < session_low

        macd_hist = float(row.get("macd_hist", 0))
        trend_strength = float(row.get("trend_strength_20", 0))
        volume_ratio = float(row.get("vol_ratio_5", 1))
        zscore = float(row.get("zclose_20", 0))
        vwap_dev = float(row.get("vwap_dev", 0))

        if breakout_up and macd_hist > 0:
            side = "buy"
            confidence = np.clip(0.5 + 0.2 * trend_strength + 0.1 * volume_ratio + 0.1 * zscore - 0.1 * abs(vwap_dev), 0, 2)
            rationale = "Momentum breakout above session high"
            stop = price - max(0.5, float(row.get("atr_14", 0)))
            target = price + max(0.5, float(row.get("atr_14", 0)) * 1.5)
        elif breakout_down and macd_hist < 0:
            side = "sell"
            confidence = np.clip(0.5 + 0.2 * trend_strength + 0.1 * volume_ratio + 0.1 * (-zscore) - 0.1 * abs(vwap_dev), 0, 2)
            rationale = "Momentum breakdown below session low"
            stop = price + max(0.5, float(row.get("atr_14", 0)))
            target = price - max(0.5, float(row.get("atr_14", 0)) * 1.5)
        else:
            return None

        return SignalCandidate(
            kind="equity",
            symbol=symbol,
            side=side,
            entry=float(price),
            stop=float(stop),
            target=float(target),
            confidence=float(confidence),
            rationale=rationale,
            meta={"strategy": "intraday_momentum"},
        )

    def _mean_reversion(self, symbol: str, df: pd.DataFrame, feature_row: pd.Series, quote: dict) -> SignalCandidate | None:
        row = feature_row
        if not self._liquidity_pass(row, quote):
            return None

        price = float(df["close"].iloc[-1])
        rsi2 = float(row.get("rsi_2", 50))
        rsi14 = float(row.get("rsi_14", 50))
        bb_lower = float(row.get("bb_lower_20", price))
        bb_upper = float(row.get("bb_upper_20", price))
        bb_pos = float(row.get("bb_pos_20", 0.5))
        atr_val = float(row.get("atr_14", 0))

        if rsi2 < 10 and price < bb_lower:
            side = "buy"
            distance = (bb_lower - price) / (price + 1e-9)
            confidence = np.clip(0.4 + 0.3 * distance + 0.2 * (50 - rsi2) / 50 + 0.1 * (50 - rsi14) / 50, 0, 2)
            rationale = "Mean reversion long after lower band pierce"
            stop = price - max(0.5, atr_val)
            target = price + max(0.5, atr_val * 1.2)
        elif rsi2 > 90 and price > bb_upper:
            side = "sell"
            distance = (price - bb_upper) / (price + 1e-9)
            confidence = np.clip(0.4 + 0.3 * distance + 0.2 * (rsi2 - 50) / 50 + 0.1 * (rsi14 - 50) / 50, 0, 2)
            rationale = "Mean reversion short after upper band pierce"
            stop = price + max(0.5, atr_val)
            target = price - max(0.5, atr_val * 1.2)
        else:
            return None

        return SignalCandidate(
            kind="equity",
            symbol=symbol,
            side=side,
            entry=float(price),
            stop=float(stop),
            target=float(target),
            confidence=float(confidence),
            rationale=rationale,
            meta={"strategy": "intraday_mean_reversion", "bb_pos": bb_pos},
        )

    def _swing_breakout(self, symbol: str, df: pd.DataFrame) -> SignalCandidate | None:
        feature_df, _ = build_features(df)
        if feature_df.empty:
            return None
        row = feature_df.iloc[-1]
        price = float(df["close"].iloc[-1])
        donchian_high = float(row.get("donchian_high_20", price))
        donchian_low = float(row.get("donchian_low_20", price))
        atr_val = float(row.get("atr_14", 1))
        trend_strength = float(row.get("trend_strength_20", 0))
        mom = float(row.get("mom_10", 0))

        if price > donchian_high and mom > 0:
            side = "buy"
            entry = price
            stop = price - max(atr_val, 1.0)
            target = price + atr_val * 2
            confidence = np.clip(0.6 + 0.2 * trend_strength + 0.1 * (mom / (atr_val + 1e-9)), 0, 2)
            rationale = "Swing breakout above Donchian high"
        elif price < donchian_low and mom < 0:
            side = "sell"
            entry = price
            stop = price + max(atr_val, 1.0)
            target = price - atr_val * 2
            confidence = np.clip(0.6 + 0.2 * trend_strength + 0.1 * (-mom / (atr_val + 1e-9)), 0, 2)
            rationale = "Swing breakdown below Donchian low"
        else:
            return None

        return SignalCandidate(
            kind="equity",
            symbol=symbol,
            side=side,
            entry=float(entry),
            stop=float(stop),
            target=float(target),
            confidence=float(confidence),
            rationale=rationale,
            meta={"strategy": "swing_breakout", "atr": atr_val},
        )

    def _options_spreads(self, equity_signal: SignalCandidate, chain: dict) -> list[SignalCandidate]:
        if not chain:
            chain = {"options": []}
        options = chain.get("options", [])
        target_delta_low, target_delta_high = self.config.option_delta
        filtered = [
            opt for opt in options
            if target_delta_low <= abs(float(opt.get("delta", 0))) <= target_delta_high
            and int(opt.get("open_interest", 0)) >= self.config.min_option_oi
        ]
        if not filtered:
            filtered = options[:1]
        candidates: list[SignalCandidate] = []
        for opt in filtered[:2]:
            debit = float(opt.get("ask", 0)) - float(opt.get("bid", 0)) / 2
            meta = {
                "underlying": equity_signal.symbol,
                "strike": opt.get("strike"),
                "expiry": opt.get("expiry"),
                "delta": opt.get("delta"),
                "est_debit": max(debit, 0.01),
            }
            candidates.append(
                SignalCandidate(
                    kind="option",
                    symbol=f"{equity_signal.symbol} {opt.get('strike')} {opt.get('type', '').upper()}",
                    side="buy" if equity_signal.side == "buy" else "sell",
                    entry=float(meta["est_debit"]),
                    stop=None,
                    target=None,
                    confidence=float(np.clip(equity_signal.confidence * 0.8, 0, 2)),
                    rationale=f"Debit spread aligned with {equity_signal.meta.get('strategy')}",
                    meta=meta,
                )
            )
        if not candidates:
            candidates.append(
                SignalCandidate(
                    kind="option",
                    symbol=f"{equity_signal.symbol} synthetic",
                    side=equity_signal.side,
                    entry=0.5,
                    stop=None,
                    target=None,
                    confidence=float(np.clip(equity_signal.confidence * 0.6, 0, 2)),
                    rationale="Placeholder debit spread",
                    meta={"underlying": equity_signal.symbol},
                )
            )
        return candidates

    def _rank(self, candidate: SignalCandidate, feature_row: pd.Series | None = None) -> float:
        liquidity_proxy = 0.0
        spread_penalty = 0.0
        if feature_row is not None:
            dollar_vol = float(feature_row.get("dollar_vol_20", 0))
            atr_val = float(feature_row.get("atr_14", 1))
            spread_penalty = float(feature_row.get("spread_bps", 0)) / 1000
            liquidity_proxy = min(1.0, dollar_vol / 1e7) + min(1.0, atr_val / 5)
        score = candidate.confidence + liquidity_proxy - spread_penalty
        return float(np.clip(score, 0, 2))

    def produce(self, profile: str = "balanced", universe: Iterable[str] | None = None) -> SignalBundle:
        symbols = list(universe or self.config.universe)
        candidates: dict[tuple[str, str], tuple[SignalCandidate, float]] = {}

        for symbol in symbols:
            try:
                intraday_df = self._fetch_bars(symbol, self.config.tf_intraday, self.config.lookback)
            except FileNotFoundError:
                logger.info("Missing intraday data for %s", symbol)
                continue
            if len(intraday_df) < self.config.min_session_bars:
                continue
            quote_df = None
            quote = {}
            try:
                quote = self._fetch_quote(symbol)
                if quote:
                    quote_df = pd.DataFrame([quote])
            except Exception:  # pragma: no cover
                quote_df = None

            feature_df, _ = build_features(intraday_df, quote_df)
            if feature_df.empty:
                continue
            feature_row = feature_df.iloc[-1]

            if self.config.enable_momo:
                candidate = self._intraday_momentum(symbol, intraday_df, feature_row, quote)
                if candidate:
                    preview = intraday_df.tail(120)[["time", "open", "high", "low", "close", "volume"]].to_dict(orient="records")
                    candidate.meta = {**candidate.meta, "preview_bars": preview, "session_vwap": float(feature_row.get("session_vwap", candidate.entry))}
                    rank = self._rank(candidate, feature_row)
                    key = (candidate.symbol, candidate.side)
                    if key not in candidates or rank > candidates[key][1]:
                        candidates[key] = (candidate, rank)

            if self.config.enable_revert:
                candidate = self._mean_reversion(symbol, intraday_df, feature_row, quote)
                if candidate:
                    preview = intraday_df.tail(120)[["time", "open", "high", "low", "close", "volume"]].to_dict(orient="records")
                    candidate.meta = {**candidate.meta, "preview_bars": preview, "session_vwap": float(feature_row.get("session_vwap", candidate.entry))}
                    rank = self._rank(candidate, feature_row)
                    key = (candidate.symbol, candidate.side)
                    if key not in candidates or rank > candidates[key][1]:
                        candidates[key] = (candidate, rank)

            if self.config.enable_swing:
                try:
                    swing_df = self._fetch_bars(symbol, self.config.tf_swing, 200)
                    if len(swing_df) >= 30:
                        candidate = self._swing_breakout(symbol, swing_df)
                        if candidate:
                            feature_df, _ = build_features(swing_df)
                            feature_row = feature_df.iloc[-1] if not feature_df.empty else None
                            preview = swing_df.tail(60)[["time", "open", "high", "low", "close", "volume"]].to_dict(orient="records")
                            candidate.meta = {**candidate.meta, "preview_bars": preview}
                            rank = self._rank(candidate, feature_row)
                            key = (candidate.symbol, candidate.side)
                            if key not in candidates or rank > candidates[key][1]:
                                candidates[key] = (candidate, rank)
                except FileNotFoundError:
                    logger.info("Missing swing data for %s", symbol)
                    continue

        sorted_candidates = sorted(candidates.values(), key=lambda x: x[1], reverse=True)
        final_candidates: list[SignalCandidate] = []
        for candidate, rank in sorted_candidates[: self.config.top_n]:
            final_candidates.append(candidate.copy())
            if self.config.enable_options and candidate.kind == "equity":
                try:
                    chain = self.client.get_option_chain(candidate.symbol)
                except Exception:
                    chain = {"options": []}
                final_candidates.extend(self._options_spreads(candidate, chain))

        bundle = SignalBundle(
            generated_at=datetime.utcnow(),
            profile=profile,
            candidates=final_candidates,
        )
        try:
            jlog(
                "signal.candidates",
                count=len(final_candidates),
                profile=profile,
                symbols=[c.symbol for c in final_candidates][:20],
            )
        except Exception:  # pragma: no cover - logging best effort
            logger.debug("failed to emit signal.candidates log", exc_info=True)
        return bundle
