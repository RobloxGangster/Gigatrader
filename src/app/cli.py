from __future__ import annotations

import asyncio
import datetime
import os
import signal
import time
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from app.alpaca_client import build_trading_client
from app.execution.alpaca_orders import (
    build_limit_order,
    build_market_order,
    submit_order_sync,
)
from app.streaming import _select_feed_with_probe, stream_bars

console = Console()
app = typer.Typer(add_completion=False)


def _load_env() -> None:
    load_dotenv()


def _pick_config(cfg: str | None) -> str:
    return cfg or "config.yaml"


def _warn_missing_keys() -> None:
    if not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_API_SECRET"):
        console.print("[yellow]Warning: missing ALPACA keys; some features will fail[/yellow]")


@app.command()
def status() -> None:
    _load_env()
    _warn_missing_keys()
    try:
        client = build_trading_client()
        account = client.get_account()
        mode = "LIVE" if os.getenv("LIVE_TRADING", "").lower() == "true" else "PAPER"
        console.print(
            f"Mode={mode} status={account.status} equity={account.portfolio_value}"
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]status error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def paper(config: str = typer.Option(None, "--config")) -> None:
    _load_env()
    _warn_missing_keys()
    cfg = _pick_config(config)
    os.environ["PROFILE"] = "paper"
    os.environ["LIVE_TRADING"] = ""
    console.rule("[bold cyan]Paper Trading")
    console.print(Panel.fit(f"Config: {cfg}", title="Using Config", border_style="cyan"))
    console.print("[green]Running. Press Ctrl+C to stop.[/green]")
    stop = False

    def _sigint(_sig, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sigint)
    i = 0
    while not stop:
        console.print(f"[dim]{datetime.datetime.now().strftime('%H:%M:%S')}[/dim] heartbeat #{i+1}")
        time.sleep(1.0)
        i += 1
    console.print("[yellow]Stopped by user.[/yellow]")


@app.command()
def verify_feed() -> None:
    _load_env()
    _warn_missing_keys()
    try:
        feed = _select_feed_with_probe()
        console.print(f"[green]Selected feed:[/green] {str(feed).split('.')[-1]}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Feed selection failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def feed_latency(symbols: str = "AAPL,MSFT", seconds: int = 20) -> None:
    _load_env()
    _warn_missing_keys()
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    health: list[dict] = []

    def on_health(h):
        health.append(h)

    duration_min = seconds / 60 if seconds else None
    try:
        asyncio.run(stream_bars(syms, minutes=duration_min, on_health=on_health))
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        pass
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]stream error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        if health:
            last = health[-1]
            stale = last.get("stale", [])
            console.print(f"Feed={last.get('feed')} stale={stale}")


@app.command()
def place_test_order(
    type: str = "market",
    symbol: str = "AAPL",
    qty: int = 1,
    limit_price: float | None = typer.Option(None, "--limit-price"),
) -> None:
    _load_env()
    _warn_missing_keys()
    if os.getenv("LIVE_TRADING", "").lower() == "true":
        console.print("[red]Refusing in LIVE. Paper only.[/red]")
        raise typer.Exit(code=2)
    client = build_trading_client()
    if type.lower() == "market":
        req = build_market_order(symbol, qty, "buy", "DAY")
    elif type.lower() == "limit":
        if limit_price is None:
            console.print("[red]limit orders require --limit-price[/red]")
            raise typer.Exit(code=2)
        req = build_limit_order(symbol, qty, "buy", float(limit_price), "DAY")
    else:
        console.print("[red]type must be market|limit[/red]")
        raise typer.Exit(code=2)
    order = submit_order_sync(client, req)
    console.print(
        f"[green]Submitted[/green] id={getattr(order, 'id', '?')} status={getattr(order, 'status', '?')}"
    )


@app.command()
def doctor() -> None:
    _load_env()
    console.rule("[bold]Gigatrader Doctor")
    ok = True
    try:
        import alpaca  # noqa: F401

        console.print("[green]alpaca-py import OK[/green]")
    except Exception as exc:  # noqa: BLE001
        ok = False
        console.print(f"[red]alpaca-py import FAIL:[/red] {exc}")
    if not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_API_SECRET"):
        ok = False
        console.print("[red]Missing ALPACA_API_KEY/ALPACA_API_SECRET[/red]")
    else:
        console.print("[green]ALPACA keys present[/green]")
    try:
        from app.data.entitlement import sip_entitled

        entitled = sip_entitled()
        console.print(f"[green]SIP entitlement probe:[/green] {entitled}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        console.print(f"[red]SIP probe error:[/red] {exc}")
    try:
        from app.cli import app as _test_app  # noqa: F401

        console.print("[green]CLI import OK[/green]")
    except Exception as exc:  # noqa: BLE001
        ok = False
        console.print(f"[red]CLI import FAIL:[/red] {exc}")
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def backtest(config: str = typer.Option(None, "--config")) -> None:
    _load_env()
    cfg = _pick_config(config)
    console.print(Panel.fit(f"Running backtest with {cfg}", title="Backtest"))
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = reports / f"{stamp}_report.html"
    output.write_text("<html><body><h1>Backtest placeholder</h1></body></html>")
    console.print(f"[green]Report generated:[/green] {output}")
