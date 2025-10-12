"""Offline simulator that replays canned bars through the strategy stack."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Iterable, Sequence, Set

from services.risk.engine import RiskManager
from services.risk.state import InMemoryState
from services.sim.exec_stub import RecordingExec
from services.sim.loader import BarRow, load_bars, load_sentiment
from services.strategy.engine import StrategyEngine
from services.strategy.types import Bar


class _OptionGatewayStub:
    """Chain source stub that prevents any remote lookups during simulation."""

    def __init__(self, exec_engine: RecordingExec) -> None:
        self.exec = exec_engine
        self.risk = getattr(exec_engine, "risk", None)

    async def propose_option_trade(self, underlying: str, side: str, qty: float) -> dict:
        return {"accepted": False, "reason": "options_disabled_in_sim"}


def _parse_symbols(raw: str) -> Set[str]:
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def _parse_faults(raw: str) -> Set[str]:
    faults = {part.strip().lower() for part in raw.split(",") if part.strip()}
    faults.discard("none")
    return faults


async def _run_stream(
    strategy: StrategyEngine,
    *,
    bars: Sequence[BarRow],
    sentiment_path: str,
    symbols: Iterable[str],
    faults: Set[str],
) -> None:
    sentiment = load_sentiment(sentiment_path)
    delays = {
        "ws_drop": 0.02,
    }
    delay = delays["ws_drop"] if "ws_drop" in faults else 0.0
    for bar in bars:
        if delay:
            await asyncio.sleep(delay)
        senti = sentiment.get(bar.symbol)
        await strategy.on_bar(
            bar.symbol,
            Bar(
                ts=bar.ts,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            ),
            senti,
        )
    return None


async def run_sim() -> str:
    symbols_env = os.getenv("SIM_SYMBOLS", "AAPL,MSFT,SPY")
    symbols = sorted(_parse_symbols(symbols_env))
    bars_path = os.getenv("SIM_BARS_PATH", "data/sim/bars_1m.csv")
    sentiment_path = os.getenv("SIM_SENTI_PATH", "data/sim/sentiment.ndjson")
    max_rows = int(os.getenv("SIM_MAX_ROWS", "2000"))
    faults = _parse_faults(os.getenv("SIM_FAULTS", "none"))

    os.environ.setdefault("SYMBOLS", ",".join(symbols))
    os.environ.setdefault("STRAT_OPTION_ENABLED", "0")
    os.environ["STRAT_ORB_MIN"] = "1"
    os.environ["STRAT_REGIME_DISABLE_CHOPPY"] = "0"
    os.environ["STRAT_SENTI_MIN"] = "0.2"

    state = InMemoryState()
    risk = RiskManager(state)
    exec_engine = RecordingExec(risk=risk, state=state, faults=faults)
    option_gateway = _OptionGatewayStub(exec_engine)
    strategy = StrategyEngine(exec_engine, option_gateway, state)

    bars = list(load_bars(bars_path, set(symbols), max_rows))
    first_close_by_symbol: dict[str, float] = {}
    for row in bars:
        first_close_by_symbol.setdefault(row.symbol, row.close)

    for eq_strategy in getattr(strategy, "equity_strategies", []):
        rsi = getattr(eq_strategy, "rsi", None)
        period = int(getattr(rsi, "period", 0)) if rsi is not None else 0
        if rsi is None or period <= 0:
            continue
        gains = getattr(rsi, "gains", None)
        losses = getattr(rsi, "losses", None)
        if gains is not None and hasattr(gains, "clear"):
            gains.clear()
            for _ in range(period):
                gains.append(1.0)
        if losses is not None and hasattr(losses, "clear"):
            losses.clear()
            for _ in range(period):
                losses.append(0.0)
        first_symbol = next(iter(symbols), None)
        if first_symbol is not None:
            first_close = first_close_by_symbol.get(first_symbol)
            if first_close is not None:
                rsi.last_close = first_close

    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result_path = artifacts_dir / "sim_result.jsonl"

    await _run_stream(
        strategy,
        bars=bars,
        sentiment_path=sentiment_path,
        symbols=symbols,
        faults=faults,
    )

    with result_path.open("w", encoding="utf-8") as handle:
        for record in exec_engine.records:
            handle.write(json.dumps(record) + "\n")

    return str(result_path)


def main() -> None:
    asyncio.run(run_sim())


if __name__ == "__main__":
    main()
