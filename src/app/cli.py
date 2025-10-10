"""Typer CLI entry point for Gigatrader.

The CLI intentionally keeps the paper command runnable end-to-end so that
contributors can verify the configuration, risk presets, and orchestration
plumbing without needing real broker connectivity.  The paper session spins up
an asynchronous event loop with a heartbeat, kill-switch monitoring, and a
lightweight strategy simulation that exercises the risk manager.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import pathlib
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
for candidate in (REPO_ROOT, REPO_ROOT / "src"):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from core.config import AppConfig, RiskPresetConfig, get_alpaca_settings, load_config
from core.clock import MarketClock
from core.kill_switch import KillSwitch
from core.interfaces import Broker
from core.utils import ensure_paper_mode
from risk.manager import ConfiguredRiskManager
from strategies.equities_momentum import EquitiesMomentumStrategy
from app.data.quality import FeedHealth, get_data_staleness_seconds
from app.streaming import stream_bars, _select_feed_with_probe, monitor_feed
from app.execution.alpaca_orders import (
    submit_order_sync,
    build_market_order,
    build_limit_order,
)
from app.alpaca_client import build_trading_client, MissingCredentialsError

try:  # pragma: no cover - optional import for error handling
    from alpaca.common.exceptions import APIError
except ModuleNotFoundError:  # pragma: no cover - fallback when alpaca-py missing
    class APIError(Exception):  # type: ignore
        """Fallback API error type when alpaca-py is absent."""

app = typer.Typer(add_completion=False, help="Gigatrader trading CLI")
trade_app = typer.Typer(help="Direct trading utilities")
app.add_typer(trade_app, name="trade")
console = Console()
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"
FALLBACK_CONFIG = REPO_ROOT / "config.example.yaml"
DEFAULT_KILL_FILE = REPO_ROOT / ".kill_switch"
LOGGER = logging.getLogger(__name__)


def _load_env() -> bool:
    """Load environment variables from the project-level ``.env`` file."""

    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
        return True
    return False


def _pick_config(explicit: Optional[str]) -> pathlib.Path:
    """Resolve the configuration file path used for the session."""

    if explicit:
        candidate = pathlib.Path(explicit)
        if candidate.exists():
            return candidate
        console.print(
            f"[yellow]Config not found at {candidate} — continuing with fallback if available.[/yellow]"
        )
    if DEFAULT_CONFIG.exists():
        return DEFAULT_CONFIG
    if FALLBACK_CONFIG.exists():
        console.print(
            f"[yellow]Using fallback config: {FALLBACK_CONFIG.name}. Create config.yaml to override.[/yellow]"
        )
        return FALLBACK_CONFIG
    console.print("[red]No config file found. Please create config.yaml or keep config.example.yaml.[/red]")
    raise typer.Exit(code=1)


def _warn_missing_keys() -> None:
    """Warn when expected Alpaca keys are absent from the environment."""

    settings = get_alpaca_settings()
    missing: list[str] = []
    if not settings.key_id:
        missing.append("ALPACA_KEY_ID")
    if not settings.secret_key:
        missing.append("ALPACA_SECRET_KEY")
    if missing:
        console.print(
            "[yellow]Missing env keys: {}. Paper mode works without them, but add them later in .env.[/yellow]".format(
                ", ".join(missing)
            )
        )


def _parse_symbols(raw: str) -> list[str]:
    """Normalise a comma-delimited symbol string."""

    return [token.strip().upper() for token in raw.split(",") if token.strip()]


def _fetch_market_clock() -> Optional[MarketClock]:
    """Return the broker clock when credentials and alpaca-py are available."""

    try:
        from alpaca.trading.client import TradingClient  # type: ignore
    except ModuleNotFoundError:
        return None

    settings = get_alpaca_settings()
    if not settings.key_id or not settings.secret_key:
        return None
    paper = ensure_paper_mode(default=True) != "live"
    client = TradingClient(settings.key_id, settings.secret_key, paper=paper)
    try:
        clock = client.get_clock()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to fetch broker clock: %s", exc)
        return None
    return MarketClock(
        timestamp=clock.timestamp,
        is_open=clock.is_open,
        next_open=clock.next_open,
        next_close=clock.next_close,
    )


def _format_ts(value: Optional[dt.datetime]) -> str:
    if value is None:
        return "—"
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _format_latency(latency: dict) -> str:
    p50 = latency.get("p50")
    p95 = latency.get("p95")
    if p50 is None or p95 is None:
        return "n/a"
    return f"{p50:.3f}s / {p95:.3f}s"


def _render_feed_summary(feed_health: FeedHealth, header: str) -> None:
    table = Table(title=header)
    table.add_column("Symbol", style="cyan", justify="left")
    table.add_column("Status", justify="left")
    table.add_column("Last Event (UTC)")
    table.add_column("Latency p50/p95")
    for entry in feed_health.snapshot():
        table.add_row(
            entry["symbol"],
            entry["status"],
            _format_ts(entry["last_event_ts"]),
            _format_latency(entry["latency"]),
        )
    console.print(table)


def _render_mismatches(mismatches: list[dict]) -> None:
    if not mismatches:
        return
    table = Table(title="Snapshot vs stream mismatches")
    table.add_column("Symbol", style="cyan")
    table.add_column("Time Δ (s)")
    table.add_column("Stream TS")
    table.add_column("Snapshot TS")
    table.add_column("Price Δ")
    for item in mismatches:
        price_delta = item.get("price_delta")
        price_cell = f"{price_delta:.4f}" if price_delta is not None else "n/a"
        table.add_row(
            item["symbol"],
            f"{item['delta_seconds']:.3f}",
            _format_ts(item.get("stream_timestamp")),
            _format_ts(item.get("snapshot_timestamp")),
            price_cell,
        )
    console.print(table)


def _extract_order_id(order: object) -> Optional[str]:
    """Best-effort extraction of an Alpaca order identifier."""

    if order is None:
        return None
    for attr in ("id", "order_id", "client_order_id"):
        if hasattr(order, attr):
            value = getattr(order, attr)
            if value:
                return str(value)
    if hasattr(order, "model_dump"):
        payload = order.model_dump()
        for key in ("id", "order_id", "client_order_id"):
            value = payload.get(key)
            if value:
                return str(value)
    if isinstance(order, dict):
        for key in ("id", "order_id", "client_order_id"):
            value = order.get(key)
            if value:
                return str(value)
    return None


@trade_app.command("place-test-order")
def place_test_order(
    order_type: str = typer.Option("market", "--type", help="Order type: market or limit"),
    symbol: str = typer.Option("AAPL", "--symbol", help="Ticker symbol to trade"),
    qty: int = typer.Option(1, "--qty", min=1, help="Share quantity for the test order"),
    limit_price: Optional[float] = typer.Option(
        None, "--limit-price", help="Required when --type=limit"
    ),
) -> None:
    """Submit a tiny paper order then attempt to cancel it."""

    _load_env()
    if os.getenv("LIVE_TRADING", "false").lower() == "true":
        console.print("[red]Refusing to place test order while LIVE_TRADING is true.[/red]")
        raise typer.Exit(code=2)

    try:
        client = build_trading_client(force_paper=True)
    except MissingCredentialsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    client_order_id = f"test-{uuid.uuid4().hex[:12]}"
    side = "buy"
    order_type_value = order_type.lower()
    try:
        if order_type_value == "market":
            request = build_market_order(
                symbol, qty, side, tif="DAY", client_order_id=client_order_id
            )
        elif order_type_value == "limit":
            if limit_price is None:
                console.print("[red]limit orders require --limit-price[/red]")
                raise typer.Exit(code=2)
            request = build_limit_order(
                symbol,
                qty,
                side,
                limit_price,
                tif="DAY",
                client_order_id=client_order_id,
            )
        else:
            console.print("[red]--type must be either 'market' or 'limit'.[/red]")
            raise typer.Exit(code=2)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    try:
        order = submit_order_sync(client, request)
    except APIError as exc:
        console.print(f"[red]Order submission failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001 - guard unexpected failures
        console.print(f"[red]Order submission failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    order_id = _extract_order_id(order)
    console.print(
        "[green]Submitted paper order[/green] {symbol} x{qty} (client_id={client_order_id})".format(
            symbol=symbol,
            qty=qty,
            client_order_id=client_order_id,
        )
    )

    if not order_id:
        console.print("[yellow]Order id missing from response; skipping cancel step.[/yellow]")
        return

    cancel_failed = False
    try:
        client.cancel_order_by_id(order_id)
        console.print(f"[yellow]Cancel requested for order {order_id}[/yellow]")
    except Exception as exc:  # noqa: BLE001 - best-effort cancel
        console.print(f"[yellow]Order submitted but cancel failed: {exc}[/yellow]")
        cancel_failed = True

    if cancel_failed:
        raise typer.Exit(code=1)


@trade_app.command("verify-feed")
def verify_feed_command() -> None:
    """Print the selected market data feed after performing entitlement checks."""

    _load_env()
    try:
        feed = _select_feed_with_probe()
    except Exception as exc:  # noqa: BLE001 - propagate failures as CLI error
        console.print(f"[red]Feed selection failed[/red]: {exc}")
        raise typer.Exit(code=1) from exc

    feed_name = feed.name if hasattr(feed, "name") else str(feed)
    console.print(f"[green]Selected feed:[/green] {feed_name}")


@trade_app.command("feed-latency")
def trade_feed_latency(
    symbols: str = typer.Option("AAPL,MSFT", "--symbols", help="Comma-separated tickers to monitor"),
    seconds: int = typer.Option(30, "--seconds", min=5, help="Duration to stream in seconds"),
) -> None:
    """Stream briefly and report per-symbol latency/staleness stats."""

    _load_env()
    symbol_list = _parse_symbols(symbols)
    if not symbol_list:
        console.print("[red]Provide at least one symbol via --symbols.[/red]")
        raise typer.Exit(code=1)

    health_updates: list[dict] = []

    async def _runner() -> None:
        await stream_bars(
            symbol_list,
            minutes=seconds / 60.0,
            on_health=health_updates.append,
        )

    try:
        asyncio.run(_runner())
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if not health_updates:
        console.print("[yellow]No health updates received; feed may be unavailable.[/yellow]")
        raise typer.Exit(code=1)

    last = health_updates[-1]
    feed_name = last.get("feed", "?")
    console.print(f"[green]Feed:[/green] {feed_name}")
    stale_symbols = last.get("stale", [])
    if stale_symbols:
        console.print(
            "[red]Symbols reported stale:[/red] {}".format(", ".join(stale_symbols))
        )
    latency = last.get("latency", {})
    for sym in symbol_list:
        stats = latency.get(sym, {})
        p50 = stats.get("p50")
        p95 = stats.get("p95")
        console.print(
            "[cyan]{sym}[/cyan] p50={p50} p95={p95}".format(
                sym=sym,
                p50=f"{p50:.3f}s" if p50 is not None else "n/a",
                p95=f"{p95:.3f}s" if p95 is not None else "n/a",
            )
        )

    if stale_symbols:
        raise typer.Exit(code=1)

@app.command("verify-data")
def verify_data(
    symbols: str = typer.Option("AAPL,MSFT", "--symbols", help="Comma-separated tickers to monitor"),
    minutes: int = typer.Option(5, "--minutes", min=1, help="Duration to stream in minutes"),
    staleness_sec: Optional[int] = typer.Option(
        None, "--staleness-sec", help="Override DATA_STALENESS_SEC for this run"
    ),
) -> None:
    """Stream live bars and report feed health diagnostics."""

    _load_env()
    _warn_missing_keys()
    symbol_list = _parse_symbols(symbols)
    if not symbol_list:
        console.print("[red]Provide at least one symbol via --symbols.[/red]")
        raise typer.Exit(code=1)

    feed_health = FeedHealth()
    clock = _fetch_market_clock()
    if clock:
        feed_health.set_market_open(clock.is_open)
        if not clock.is_open:
            console.print(
                "[yellow]Market appears closed; staleness watchdog is paused until next open.[/yellow]"
            )
    else:
        feed_health.set_market_open(True)
        console.print("[yellow]Broker clock unavailable; assuming market open.[/yellow]")

    staleness = staleness_sec or get_data_staleness_seconds()
    try:
        asyncio.run(_run_stream_session(symbol_list, minutes * 60, feed_health, staleness))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _render_feed_summary(feed_health, f"Feed verification ({minutes} minutes)")
    mismatches = []
    try:
        mismatches = feed_health.crosscheck_snapshot(symbol_list)
    except RuntimeError as exc:
        console.print(f"[yellow]Snapshot cross-check skipped: {exc}[/yellow]")
    else:
        _render_mismatches(mismatches)

    stale_symbols = [row["symbol"] for row in feed_health.snapshot() if row["status"] == "STALE"]
    if stale_symbols:
        console.print(
            "[red]Feed reported as STALE for: {}[/red]".format(", ".join(sorted(stale_symbols)))
        )
        raise typer.Exit(code=2)


@app.command("feed-latency")
def feed_latency(
    symbols: str = typer.Option("AAPL,MSFT", "--symbols", help="Comma-separated tickers to monitor"),
    seconds: int = typer.Option(30, "--seconds", min=5, help="Duration to stream in seconds"),
    staleness_sec: Optional[int] = typer.Option(
        None, "--staleness-sec", help="Override DATA_STALENESS_SEC for this run"
    ),
) -> None:
    """Report latency statistics for the configured feed."""

    _load_env()
    symbol_list = _parse_symbols(symbols)
    if not symbol_list:
        console.print("[red]Provide at least one symbol via --symbols.[/red]")
        raise typer.Exit(code=1)

    feed_health = FeedHealth()
    clock = _fetch_market_clock()
    if clock:
        feed_health.set_market_open(clock.is_open)
        if not clock.is_open:
            console.print(
                "[yellow]Market appears closed; latency stats may reflect idle feed conditions.[/yellow]"
            )
    staleness = staleness_sec or get_data_staleness_seconds()
    try:
        asyncio.run(_run_stream_session(symbol_list, seconds, feed_health, staleness))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _render_feed_summary(feed_health, f"Feed latency ({seconds} seconds)")
    stale_symbols = [row["symbol"] for row in feed_health.snapshot() if row["status"] == "STALE"]
    if stale_symbols:
        console.print(
            "[red]Feed reported as STALE for: {}[/red]".format(", ".join(sorted(stale_symbols)))
        )
        raise typer.Exit(code=2)


async def _run_stream_session(
    symbols: list[str], duration_seconds: int, feed_health: FeedHealth, staleness_sec: int
) -> None:
    await monitor_feed(
        symbols,
        duration_seconds,
        feed_health=feed_health,
        staleness_sec=staleness_sec,
    )


@dataclass(slots=True)
class PaperRuntimeContext:
    """Shared runtime artefacts for the paper session."""

    config: AppConfig
    risk_preset: RiskPresetConfig
    risk_manager: ConfiguredRiskManager
    strategy: EquitiesMomentumStrategy
    kill_switch: KillSwitch
    broker: Optional[Broker] = None


class PaperTradingSession:
    """Drives the asynchronous paper trading simulation."""

    def __init__(
        self,
        config_path: pathlib.Path,
        risk_override: Optional[str] = None,
        bar_interval: float = 5.0,
    ) -> None:
        self._config_path = config_path
        self._risk_override = risk_override
        self._bar_interval = bar_interval
        self._stop = asyncio.Event()
        self._run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self._portfolio_state = {"daily_loss": 0.0, "open_positions": 0}

    async def run(self, max_iterations: Optional[int] = None) -> None:
        """Execute the paper session until stopped."""

        context = self._build_context()
        console.rule("[bold cyan]Paper Trading Session")
        console.print(self._session_panel(context))
        console.print(
            "[green]Starting paper run. Press Ctrl+C or engage the kill switch to stop.[/green]"
        )

        heartbeat = asyncio.create_task(self._heartbeat_loop())
        monitor = asyncio.create_task(self._monitor_kill_switch(context.kill_switch))
        strategy_task = asyncio.create_task(
            self._strategy_loop(context, max_iterations=max_iterations)
        )

        try:
            await self._stop.wait()
        except asyncio.CancelledError:
            console.print("[yellow]Cancellation received; shutting down paper session…[/yellow]")
            raise
        finally:
            for task in (heartbeat, monitor, strategy_task):
                task.cancel()
            await asyncio.gather(heartbeat, monitor, strategy_task, return_exceptions=True)
            console.print("[green]Paper run stopped.[/green]")

    def request_stop(self) -> None:
        """Allow external callers to stop the session."""

        if not self._stop.is_set():
            self._stop.set()

    def _build_context(self) -> PaperRuntimeContext:
        config = load_config(self._config_path)
        preset_key = self._risk_override or config.risk_profile
        try:
            risk_preset = config.risk_presets[preset_key]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise typer.BadParameter(
                f"Risk preset '{preset_key}' not defined in configuration"
            ) from exc

        kill_switch = KillSwitch(path=DEFAULT_KILL_FILE)
        risk_manager = ConfiguredRiskManager(risk_preset.model_dump(), kill_switch)
        strategy = EquitiesMomentumStrategy(config.data.symbols)
        broker = self._maybe_create_broker(config)

        return PaperRuntimeContext(
            config=config,
            risk_preset=risk_preset,
            risk_manager=risk_manager,
            strategy=strategy,
            kill_switch=kill_switch,
            broker=broker,
        )

    def _maybe_create_broker(self, config: AppConfig) -> Optional[Broker]:
        venue = config.execution.venue.lower()
        if venue != "alpaca":
            return None

        settings = get_alpaca_settings()
        missing: list[str] = []
        if not settings.key_id:
            missing.append("ALPACA_KEY_ID")
        if not settings.secret_key:
            missing.append("ALPACA_SECRET_KEY")
        if missing:
            console.print(
                "[yellow]Alpaca credentials missing ({}); continuing with simulated fills.[/yellow]".format(
                    ", ".join(missing)
                )
            )
            return None

        try:
            from alpaca.trading.client import TradingClient
        except ModuleNotFoundError:
            console.print(
                "[yellow]alpaca-py not installed; install alpaca-py to forward paper orders to Alpaca.[/yellow]"
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive guard
            console.print(
                f"[yellow]Unable to initialise Alpaca client ({exc!r}); continuing with simulated fills.[/yellow]"
            )
            return None

        try:
            from execution.alpaca_broker import AlpacaBroker
        except ModuleNotFoundError:
            console.print(
                "[yellow]Alpaca broker adapter unavailable; continuing with simulated fills.[/yellow]"
            )
            return None

        paper_env = ensure_paper_mode(default=True) == "paper"
        endpoint = settings.paper_endpoint if paper_env else settings.live_endpoint
        try:
            client = TradingClient(
                settings.key_id,
                settings.secret_key,
                paper=paper_env,
                url_override=endpoint,
            )
        except TypeError as exc:  # pragma: no cover - stub fallback
            console.print(
                f"[yellow]alpaca-py TradingClient stub detected ({exc}); continuing with simulated fills.[/yellow]"
            )
            return None
        console.print("[green]Forwarding paper orders to Alpaca {} trading.[/green]".format("paper" if paper_env else "live"))
        return AlpacaBroker(client)

    def _session_panel(self, context: PaperRuntimeContext) -> Panel:
        preset = context.risk_preset
        table = Table.grid(padding=(0, 1))
        table.add_row("Run ID", self._run_id)
        table.add_row("Profile", context.config.profile)
        table.add_row("Risk Preset", preset.name)
        table.add_row("Universe", ", ".join(context.strategy.state.universe) or "(empty)")
        table.add_row("Timeframes", ", ".join(context.config.data.timeframes))
        table.add_row("Max Positions", str(preset.max_positions))
        table.add_row("Daily Loss Limit", f"${preset.daily_loss_limit:,.0f}")
        return Panel.fit(table, title="Session Summary", border_style="cyan")

    async def _heartbeat_loop(self) -> None:
        try:
            while not self._stop.is_set():
                console.print(
                    f"[dim]{dt.datetime.now().strftime('%H:%M:%S')}[/dim] heartbeat: run {self._run_id} ok"
                )
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            pass

    async def _monitor_kill_switch(self, kill_switch: KillSwitch) -> None:
        try:
            while not self._stop.is_set():
                if await kill_switch.engaged():
                    console.print("[red]Kill switch engaged. Stopping paper run.[/red]")
                    self._stop.set()
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            pass

    async def _strategy_loop(
        self,
        context: PaperRuntimeContext,
        *,
        max_iterations: Optional[int],
    ) -> None:
        symbols = context.strategy.state.universe or ["AAPL"]
        atr_lookup = {symbol: 3.0 for symbol in symbols}
        await context.strategy.prepare({"atr": atr_lookup, "regime": "neutral"})

        price_state = {symbol: 100.0 + index * 5 for index, symbol in enumerate(symbols)}
        iterations = 0

        try:
            while not self._stop.is_set():
                for symbol in symbols:
                    price_state[symbol] += 0.5
                    price = price_state[symbol]
                    atr = atr_lookup[symbol]
                    suggested_size = await context.risk_manager.size({"atr": atr})
                    qty = max(1, int(suggested_size))

                    signals = {
                        "orb_breakout": iterations % max(len(symbols), 1) == 0,
                        "momentum": 1 if iterations % 4 < 2 else -1,
                        "size": qty,
                        "target": round(price * 1.01, 2),
                        "stop": round(price * 0.99, 2),
                    }
                    bar = {"symbol": symbol, "close": price, "signals": signals}
                    orders = await context.strategy.on_bar(bar)
                    if not orders:
                        await asyncio.sleep(self._bar_interval)
                        iterations += 1
                        if max_iterations and iterations >= max_iterations:
                            console.print(
                                f"[yellow]Reached max iterations ({max_iterations}); stopping session.[/yellow]"
                            )
                            self._stop.set()
                            return
                        continue

                    for order in orders:
                        enriched = dict(order)
                        enriched.setdefault("asset_class", "us_equity")
                        enriched["notional"] = order.get("qty", 0) * price
                        decision = await context.risk_manager.pre_trade_check(
                            enriched, self._portfolio_state
                        )
                        if decision.allow:
                            broker = context.broker
                            if broker is not None:
                                try:
                                    broker_payload = dict(enriched)
                                    broker_payload.pop("notional", None)
                                    response = await broker.submit(broker_payload)
                                except Exception as exc:  # pragma: no cover - network/runtime errors
                                    console.print(
                                        f"[yellow]Failed to forward order to Alpaca ({exc!r}); falling back to simulated fill.[/yellow]"
                                    )
                                else:
                                    order_id = response.get("id", "?")
                                    console.print(
                                        "[green]Submitted to Alpaca[/green] {symbol} {side} {qty} -> id {order_id}".format(
                                            symbol=symbol,
                                            side=enriched.get("side", "?").upper(),
                                            qty=enriched.get("qty", 0),
                                            order_id=order_id,
                                        )
                                    )
                                    continue

                            console.print(
                                "[cyan]Simulated fill[/cyan] {symbol} {side} {qty} @ {price:.2f}".format(
                                    symbol=symbol,
                                    side=enriched.get("side", "?").upper(),
                                    qty=enriched.get("qty", 0),
                                    price=price,
                                )
                            )
                            await context.strategy.on_fill(
                                {
                                    "symbol": symbol,
                                    "qty": enriched.get("qty", 0),
                                    "fill_price": price,
                                    "side": enriched.get("side"),
                                }
                            )
                        else:
                            console.print(
                                f"[yellow]Order blocked[/yellow] {symbol}: {decision.reason}"
                            )

                    await asyncio.sleep(self._bar_interval)
                    iterations += 1
                    if max_iterations and iterations >= max_iterations:
                        console.print(
                            f"[yellow]Reached max iterations ({max_iterations}); stopping session.[/yellow]"
                        )
                        self._stop.set()
                        return
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            pass


@app.command()
def paper(config: Optional[str] = typer.Option(None, "--config")):
    _load_env()
    _warn_missing_keys()
    cfg = _pick_config(config)
    os.environ["PROFILE"] = "paper"
    os.environ["LIVE_TRADING"] = ""
    console.rule("[bold cyan]Paper Trading")
    console.print(Panel.fit(f"Config: {cfg}", title="Using Config", border_style="cyan"))
    console.print("[green]Running. Press Ctrl+C to stop.[/green]")

    stop = False

    def _sigint(_s, _f):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sigint)

    i = 0
    while not stop:
        console.print(f"[dim]{dt.datetime.now().strftime('%H:%M:%S')}[/dim] heartbeat #{i+1}")
        time.sleep(1.0)
        i += 1

    console.print("[yellow]Paper run stopped by user.[/yellow]")


@app.command()
def backtest(
    config: Optional[str] = typer.Option(None, "--config", help="Path to config.yaml"),
) -> None:
    """Stub backtest command that validates configuration wiring."""

    cfg_path = _pick_config(config)
    cfg = load_config(cfg_path)
    console.rule("[bold magenta]Backtest (Stub)")
    console.print(
        f"Loaded configuration for profile [bold]{cfg.profile}[/bold] with {len(cfg.data.symbols)} symbols."
    )
    console.print("[yellow]Backtest engine integration is pending implementation.[/yellow]")


@app.command()
def live(
    config: Optional[str] = typer.Option(None, "--config", help="Path to config.yaml"),
) -> None:
    """Guarded live-trading entry point."""

    _load_env()
    cfg_path = _pick_config(config)
    cfg = load_config(cfg_path)
    if os.getenv("LIVE_TRADING", "false").lower() != "true":
        console.print("[red]Refusing to run live. Set LIVE_TRADING=true then re-run.[/red]")
        raise typer.Exit(code=2)
    console.rule("[bold red]Live Trading (Stub)")
    console.print(Panel.fit(f"Profile: {cfg.profile}", title="Using Config", border_style="red"))
    console.print("[yellow]Live trading orchestration is intentionally disabled in the scaffold.[/yellow]")


@app.command()
def halt() -> None:
    """Engage the global kill switch."""

    kill_switch = KillSwitch(path=DEFAULT_KILL_FILE)
    asyncio.run(kill_switch.engage())
    console.print("[red]Kill switch engaged.[/red]")


if __name__ == "__main__":
    app()
