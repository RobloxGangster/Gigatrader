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
import os
import pathlib
import sys
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

from core.config import AppConfig, RiskPresetConfig, load_config
from core.kill_switch import KillSwitch
from risk.manager import ConfiguredRiskManager
from strategies.equities_momentum import EquitiesMomentumStrategy

app = typer.Typer(add_completion=False, help="Gigatrader trading CLI")
console = Console()
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"
FALLBACK_CONFIG = REPO_ROOT / "config.example.yaml"
DEFAULT_KILL_FILE = REPO_ROOT / ".kill_switch"


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

    missing: list[str] = []
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_BASE_URL"):
        if not os.getenv(key):
            missing.append(key)
    if missing:
        console.print(
            "[yellow]Missing env keys: {}. Paper mode works without them, but add them later in .env.[/yellow]".format(
                ", ".join(missing)
            )
        )


@dataclass(slots=True)
class PaperRuntimeContext:
    """Shared runtime artefacts for the paper session."""

    config: AppConfig
    risk_preset: RiskPresetConfig
    risk_manager: ConfiguredRiskManager
    strategy: EquitiesMomentumStrategy
    kill_switch: KillSwitch


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

        return PaperRuntimeContext(
            config=config,
            risk_preset=risk_preset,
            risk_manager=risk_manager,
            strategy=strategy,
            kill_switch=kill_switch,
        )

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
def paper(
    config: Optional[str] = typer.Option(None, "--config", help="Path to config.yaml"),
    risk_profile: Optional[str] = typer.Option(
        None, "--risk-profile", help="Override risk preset from config"
    ),
    max_iterations: int = typer.Option(
        0,
        "--max-iterations",
        help="Hidden helper for tests — limits bar iterations before stopping",
        hidden=True,
    ),
    bar_interval: float = typer.Option(
        5.0,
        "--bar-interval",
        help="Hidden helper for tests — seconds between simulated bars",
        hidden=True,
    ),
) -> None:
    """Start the paper trading session."""

    _load_env()
    _warn_missing_keys()
    cfg_path = _pick_config(config)

    session = PaperTradingSession(
        cfg_path, risk_override=risk_profile, bar_interval=bar_interval
    )
    iterations = max_iterations if max_iterations > 0 else None

    try:
        asyncio.run(session.run(max_iterations=iterations))
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted by user. Attempting graceful shutdown…[/yellow]")
        session.request_stop()
        raise typer.Exit(code=130) from None


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
