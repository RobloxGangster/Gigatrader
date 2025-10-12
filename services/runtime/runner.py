"""Phase 7 orchestration runner wiring all subsystems together."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import sys
import time
from contextlib import suppress
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import yaml

from services.execution.engine import ExecutionEngine
from services.gateway.options import OptionGateway
from services.market.loop import MarketLoop
from services.risk.engine import RiskManager
from services.risk.state import InMemoryState
from services.runtime.logging import setup_logging, with_trace
from services.runtime.metrics import Metrics, MetricsServer
from services.sentiment.poller import Poller
from services.sentiment.store import SentiStore
from services.strategy.engine import StrategyEngine
from services.strategy.types import Bar as StrategyBar

try:  # pragma: no cover - psycopg2 import validated indirectly in unit tests
    import psycopg2
except Exception:  # pragma: no cover - optional dependency guards
    psycopg2 = None


BoolEnv = Callable[[str, bool], bool]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class MockMarketLoop:
    """Synthetic market loop used for offline test runs."""

    def __init__(
        self,
        symbols: Sequence[str],
        *,
        on_bar: Callable[[str, StrategyBar], Awaitable[None]],
        metrics: Optional[Metrics] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.symbols = list(symbols) or ["AAPL"]
        self._on_bar = on_bar
        self._metrics = metrics
        self.log = logger or logging.getLogger("gigatrader.mock-market")
        self.iterations = int(os.getenv("MOCK_ITERATIONS", "20"))
        self.interval = float(os.getenv("MOCK_BAR_INTERVAL", "0.2"))
        self._rng = random.Random(42)

    async def run(self) -> None:
        self.log.info(
            "mock_market.start",
            extra=with_trace({"symbols": self.symbols, "iterations": self.iterations}),
        )
        prices: Dict[str, float] = {symbol: 100.0 + idx for idx, symbol in enumerate(self.symbols)}
        ts = time.time()
        for iteration in range(self.iterations):
            for symbol in self.symbols:
                base = prices[symbol]
                delta = self._rng.uniform(-0.5, 0.5)
                close = max(0.01, base + delta)
                high = max(base, close) + abs(self._rng.uniform(0, 0.2))
                low = min(base, close) - abs(self._rng.uniform(0, 0.2))
                bar = StrategyBar(
                    ts=ts,
                    open=base,
                    high=high,
                    low=low,
                    close=close,
                    volume=float(100 + iteration),
                )
                await self._on_bar(symbol, bar)
                prices[symbol] = close
                if self._metrics:
                    with suppress(AttributeError):
                        self._metrics.inc("market_bars")
                        self._metrics.set("market_heartbeat", ts)
            await asyncio.sleep(self.interval)
            ts += self.interval
        self.log.info("mock_market.stop", extra=with_trace())


class Runner:
    """Coordinate the full trading pipeline with observability and shutdown."""

    def __init__(self, *, env_bool: BoolEnv = _env_bool) -> None:
        setup_logging()
        self.log = logging.getLogger("gigatrader.runner")
        self.metrics = Metrics()
        port_raw = os.getenv("SERVICE_PORT", "0")
        try:
            port = int(port_raw)
        except ValueError:
            port = 0
        self.shutdown = asyncio.Event()
        self._env_bool = env_bool
        self.market_enabled = self._env_bool("RUN_MARKET", True)
        self.mock_market = self._env_bool("MOCK_MARKET", True)
        self.sentiment_enabled = self._env_bool("RUN_SENTIMENT", True)
        self.ready_timeout = int(os.getenv("READY_CHECK_TIMEOUT_SEC", "5"))
        self.state = InMemoryState()
        self.risk = RiskManager(self.state)
        self.exec = ExecutionEngine(risk=self.risk, state=self.state)
        self.opt_gateway = OptionGateway(exec_engine=self.exec, risk_manager=self.risk)
        self.strategy = StrategyEngine(self.exec, self.opt_gateway, self.state)
        self.senti_store = SentiStore()
        self.poller: Optional[Poller] = None
        self.market_loop: Optional[MarketLoop] = None
        self.symbols: Sequence[str] = ()
        self.ms = MetricsServer(
            self.metrics,
            port,
            logger=self.log,
            health_cb=self._health_status,
            ready_cb=self._ready_status,
        )
        self._tasks: List[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Readiness & health helpers
    # ------------------------------------------------------------------
    def _alpaca_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        key = (
            os.getenv("ALPACA_API_KEY_ID")
            or os.getenv("ALPACA_API_KEY")
            or os.getenv("APCA_API_KEY_ID")
        )
        secret = (
            os.getenv("ALPACA_API_SECRET_KEY")
            or os.getenv("ALPACA_API_SECRET")
            or os.getenv("APCA_API_SECRET_KEY")
        )
        return key, secret

    def _health_status(self) -> Tuple[bool, str]:
        return True, "ok"

    def _ready_status(self) -> Tuple[bool, str]:  # pragma: no cover - exercised via integration
        errors = self.readiness_errors(strict=True)
        if errors:
            return False, "; ".join(errors)
        return True, "ready"

    def readiness_errors(self, *, strict: bool = False) -> List[str]:
        errors: List[str] = []
        key, secret = self._alpaca_credentials()
        if (self.market_enabled or strict) and not self.mock_market:
            if not key or not secret:
                errors.append("missing_alpaca_credentials")
        if self.market_enabled and strict and not self.mock_market:
            ts_url = os.getenv("TIMESCALE_URL", "")
            if not ts_url:
                errors.append("missing_timescale_url")
            elif not self._timescale_ping(ts_url):
                errors.append("timescale_unreachable")
        return errors

    def _timescale_ping(self, url: str) -> bool:
        if psycopg2 is None:
            self.log.error("ready.timescale.missing_driver", extra=with_trace())
            return False
        try:
            conn = psycopg2.connect(url, connect_timeout=self.ready_timeout)
        except Exception as exc:  # pragma: no cover - runtime dependent
            self.log.error("ready.timescale.error", extra=with_trace({"error": str(exc)}))
            return False
        with suppress(Exception):
            conn.close()
        return True

    # ------------------------------------------------------------------
    # Runtime wiring
    # ------------------------------------------------------------------
    def _check_mode(self) -> None:
        mode = os.getenv("TRADING_MODE", "paper").strip().lower()
        if mode not in {"paper", "live"}:
            raise SystemExit("TRADING_MODE must be paper or live")
        if mode == "paper":
            os.environ.setdefault("ALPACA_PAPER", "true")
        else:
            confirm = os.getenv("LIVE_CONFIRM")
            if confirm != "I_UNDERSTAND":
                raise SystemExit("LIVE mode requires LIVE_CONFIRM=I_UNDERSTAND")
        self.log.info("mode", extra=with_trace({"mode": mode}))

    def _load_market_config(self) -> Dict[str, object]:
        with open("configs/market.yaml", "r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle)
        symbols_raw = cfg.get("symbols", os.getenv("SYMBOLS", "AAPL,MSFT,SPY"))
        self.symbols = [sym.strip().upper() for sym in str(symbols_raw).split(",") if sym.strip()]
        return cfg

    def _build_poller(self) -> Optional[Poller]:
        if not self.sentiment_enabled:
            return None
        from services.sentiment.fetchers import (
            StubFetcher,
        )  # local import to avoid heavy deps by default

        fetchers = [StubFetcher("stub")]
        return Poller(store=self.senti_store, fetchers=fetchers, symbols=self.symbols)

    async def _sentiment_task(self) -> None:
        if not self.poller:
            return
        interval = max(1, int(os.getenv("SENTI_POLL_SEC", "30")))
        self.log.info("sentiment.loop.start", extra=with_trace({"interval": interval}))
        while not self.shutdown.is_set():
            try:
                result = self.poller.run_once()
                self.metrics.inc("sentiment_ticks")
                self.metrics.set("sentiment_symbols", float(len(result)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - protective
                self.metrics.inc("sentiment_errors")
                self.log.error(
                    "sentiment.loop.error",
                    extra=with_trace({"error": str(exc)}),
                )
            try:
                await asyncio.wait_for(self.shutdown.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
        self.log.info("sentiment.loop.stop", extra=with_trace())

    async def _handle_bar(self, symbol: str, bar: StrategyBar) -> None:
        score, count, _velocity = self.senti_store.get(symbol)
        sentiment_value = score if count else None
        try:
            await self.strategy.on_bar(symbol, bar, sentiment_value)
            self.metrics.inc("strategy_bars")
            self.metrics.set("last_bar_ts", bar.ts)
        except Exception as exc:  # pragma: no cover - downstream resilience
            self.metrics.inc("strategy_errors")
            self.log.error(
                "strategy.on_bar.error",
                extra=with_trace({"symbol": symbol, "error": str(exc)}),
            )

    async def _market_task(self) -> None:
        if not self.market_loop:
            return
        self.log.info("market.loop.start", extra=with_trace({"symbols": list(self.symbols)}))
        try:
            await self.market_loop.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - network resilience
            self.metrics.inc("market_errors")
            self.log.error("market.loop.error", extra=with_trace({"error": str(exc)}))
        finally:
            if self.mock_market:
                self.shutdown.set()
            self.log.info("market.loop.stop", extra=with_trace())

    async def _exec_updates_task(self) -> None:
        try:
            await self.exec.run_update_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - runtime dependent
            self.log.error("execution.updates.error", extra=with_trace({"error": str(exc)}))

    def _install_signals(self) -> None:
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":  # pragma: no cover - Windows CI not in scope
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.shutdown.set)
            except NotImplementedError:  # pragma: no cover - some event loops
                pass

    async def run(self) -> None:
        self._check_mode()
        errors = self.readiness_errors(strict=True)
        if errors:
            raise SystemExit("Runner readiness failed: " + ", ".join(errors))
        cfg = self._load_market_config()
        ts_url = os.getenv("TIMESCALE_URL", "")
        if self.market_enabled:
            if self.mock_market:
                self.market_loop = MockMarketLoop(
                    self.symbols,
                    on_bar=self._handle_bar,
                    metrics=self.metrics,
                    logger=logging.getLogger("gigatrader.market"),
                )
            else:
                self.market_loop = MarketLoop(
                    cfg,
                    ts_url,
                    on_bar=self._handle_bar,
                    metrics=self.metrics,
                    logger=logging.getLogger("gigatrader.market"),
                )
        self.poller = self._build_poller()
        self.ms.start()
        self._install_signals()
        self.log.info(
            "runner.start",
            extra=with_trace(
                {
                    "symbols": list(self.symbols),
                    "market_enabled": self.market_enabled,
                    "sentiment_enabled": self.sentiment_enabled,
                }
            ),
        )

        if self.poller:
            self._tasks.append(asyncio.create_task(self._sentiment_task(), name="sentiment"))
        if self.market_loop:
            self._tasks.append(asyncio.create_task(self._market_task(), name="market"))
        self._tasks.append(asyncio.create_task(self._exec_updates_task(), name="exec_updates"))

        try:
            await self.shutdown.wait()
        finally:
            for task in self._tasks:
                task.cancel()
            with suppress(Exception):
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self.ms.stop()
            self.log.info("runner.stop", extra=with_trace())


def main() -> None:
    asyncio.run(Runner().run())


if __name__ == "__main__":  # pragma: no cover - manual entry point
    main()
