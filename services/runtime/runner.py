"""Phase 7 orchestration runner wiring all subsystems together."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from contextlib import suppress
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import yaml

from backend.broker.adapter import get_broker
from backend.services.orchestrator import (
    drain_preopen_queue,
    set_preopen_window_active,
)
from core.runtime_flags import get_runtime_flags
from services.execution.engine import ExecutionEngine
from services.execution.option_exit_watcher import OptionExitWatcher
from services.execution.types import ExecIntent
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
        flags = get_runtime_flags()
        self.market_enabled = self._env_bool("RUN_MARKET", True)
        override = os.getenv("MOCK_MARKET")
        if override is None:
            self.mock_market = bool(flags.mock_mode)
        else:
            self.mock_market = self._env_bool("MOCK_MARKET", bool(flags.mock_mode))
        self.sentiment_enabled = self._env_bool("RUN_SENTIMENT", False)
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
        self.option_exit_enabled = self._env_bool("ENABLE_OPTION_EXITS", False)
        self.opt_tp_pct = float(os.getenv("OPT_TP_PCT", "25") or 25)
        self.opt_sl_pct = float(os.getenv("OPT_SL_PCT", "10") or 10)
        self.option_exit_poll = float(os.getenv("OPTION_EXIT_POLL_SEC", "45") or 45)
        self.option_exit_watcher: OptionExitWatcher | None = None
        if self.option_exit_enabled:
            chain_source = getattr(self.opt_gateway, "chain", None)
            self.option_exit_watcher = OptionExitWatcher(
                state=self.state,
                exec_engine=self.exec,
                chain_source=chain_source,
                poll_interval=self.option_exit_poll,
                tp_pct=self.opt_tp_pct,
                sl_pct=self.opt_sl_pct,
                cache_ttl=max(self.option_exit_poll, 30.0),
            )

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
        from services.sentiment.fetchers import AlpacaNewsFetcher

        key, secret = self._alpaca_credentials()
        if not key or not secret:
            self.log.warning(
                "sentiment.disabled.missing_creds",
                extra=with_trace(),
            )
            return None
        fetcher = AlpacaNewsFetcher(key, secret)
        return Poller(store=self.senti_store, symbols=self.symbols, fetcher=fetcher)

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

    async def _wait_with_shutdown(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self.shutdown.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return

    def _parse_clock_ts(self, value: object | None) -> Optional[datetime]:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                normalized = value.replace("Z", "+00:00")
                dt_value = datetime.fromisoformat(normalized)
            except ValueError:
                return None
            if dt_value.tzinfo is None:
                dt_value = dt_value.replace(tzinfo=timezone.utc)
            return dt_value.astimezone(timezone.utc)
        return None

    def _update_preopen_window(
        self,
        *,
        is_open: bool,
        now_dt: Optional[datetime],
        next_open_dt: Optional[datetime],
    ) -> None:
        if not self.strategy.allow_preopen:
            set_preopen_window_active(False)
            return
        if is_open or now_dt is None or next_open_dt is None:
            set_preopen_window_active(False)
            return
        seconds_to_open = (next_open_dt - now_dt).total_seconds()
        if seconds_to_open <= 0:
            set_preopen_window_active(False)
            return
        window_secs = max(0, int(self.strategy.preopen_minutes)) * 60
        active = seconds_to_open <= window_secs
        set_preopen_window_active(active)

    async def _submit_preopen_orders(self) -> None:
        intents = await drain_preopen_queue()
        if not intents:
            return
        self.log.info(
            "preopen.submit",
            extra=with_trace({"count": len(intents)}),
        )
        for intent in intents:
            exec_intent = ExecIntent(
                symbol=intent.symbol,
                side=intent.side,
                qty=float(intent.qty),
                limit_price=intent.limit_price,
                asset_class="equity",
                client_tag=intent.client_order_id or f"preopen:{intent.symbol}",
                time_in_force="opg",
                order_type=intent.order_kind,
            )
            attempts = 0
            while attempts < 2:
                try:
                    await self.exec.submit(exec_intent)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    attempts += 1
                    if attempts >= 2:
                        self.log.error(
                            "preopen.submit.failed",
                            extra=with_trace({"symbol": intent.symbol, "error": str(exc)}),
                        )
                    else:
                        await asyncio.sleep(1.0)

    async def _preopen_coordinator(self) -> None:
        if self.mock_market or not self.strategy.allow_preopen:
            set_preopen_window_active(False)
            return
        try:
            adapter = get_broker()
        except Exception as exc:  # pragma: no cover - depends on runtime config
            self.log.warning(
                "preopen.disabled",
                extra=with_trace({"error": str(exc)}),
            )
            set_preopen_window_active(False)
            return

        poll_raw = os.getenv("PREOPEN_CLOCK_POLL_SEC", "20")
        try:
            poll_interval = float(poll_raw)
        except ValueError:
            poll_interval = 20.0
        poll_interval = min(30.0, max(15.0, poll_interval))

        last_is_open: Optional[bool] = None
        while not self.shutdown.is_set():
            try:
                clock = await adapter.get_clock()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network failures live only
                self.log.error(
                    "preopen.clock.error",
                    extra=with_trace({"error": str(exc)}),
                )
                await self._wait_with_shutdown(poll_interval)
                continue

            is_open = bool(clock.get("is_open"))
            now_dt = self._parse_clock_ts(clock.get("timestamp"))
            next_open_dt = self._parse_clock_ts(clock.get("next_open"))
            self._update_preopen_window(
                is_open=is_open,
                now_dt=now_dt,
                next_open_dt=next_open_dt,
            )

            if is_open and last_is_open is False:
                await self._submit_preopen_orders()

            last_is_open = is_open
            await self._wait_with_shutdown(poll_interval)

    async def _option_exit_task(self) -> None:
        watcher = self.option_exit_watcher
        if watcher is None:
            return
        try:
            await watcher.run(self.shutdown)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - runtime guard
            self.log.error(
                "option_exit.task_failed",
                extra=with_trace({"error": str(exc)}),
            )

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
        if not self.mock_market and self.strategy.allow_preopen:
            self._tasks.append(asyncio.create_task(self._preopen_coordinator(), name="preopen"))
        if self.option_exit_watcher is not None:
            self._tasks.append(asyncio.create_task(self._option_exit_task(), name="option_exit"))

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
