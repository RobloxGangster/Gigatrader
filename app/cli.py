"""Typer-powered helper CLI for paper trading workflows."""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
app = typer.Typer(add_completion=False, help="Gigatrader operational helper")

CONFIG_OPTION = typer.Option(
    Path("config.yaml"),
    "--config",
    exists=True,
    readable=True,
    help="Configuration file to load",
)
ITERATIONS_OPTION = typer.Option(5, min=1, help="Number of synthetic ticks to emit")
BAR_INTERVAL_OPTION = typer.Option(0.1, min=0.0, help="Seconds to sleep between ticks")


def _load_env() -> None:
    """Load environment variables from the default `.env` file."""

    load_dotenv(override=False)
    os.environ.setdefault("ALPACA_PAPER", "true")


def _read_yaml_or_json(path: Path) -> dict:
    payload = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        yaml = None
    if yaml is not None:
        return yaml.safe_load(payload)
    return json.loads(payload)


def _normalise_symbols(raw: Iterable[str]) -> List[str]:
    return [item.strip().upper() for item in raw if str(item).strip()]


@app.command()
def check() -> None:
    """Perform a lightweight readiness check for the CLI utilities."""

    _load_env()
    required = ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        console.print(f"[red]NOT READY:[/red] missing {', '.join(missing)}")
        raise typer.Exit(code=1)
    console.print("[green]READY[/green]")


@app.command()
def paper(
    config: Path = CONFIG_OPTION,
    max_iterations: int = ITERATIONS_OPTION,
    bar_interval: float = BAR_INTERVAL_OPTION,
) -> None:
    """Run an offline paper trading simulation using configuration defaults."""

    _load_env()
    try:
        cfg = _read_yaml_or_json(config)
    except FileNotFoundError:
        console.print(f"[red]Missing config:[/red] {config}")
        raise typer.Exit(code=2) from None

    symbols = _normalise_symbols(cfg.get("data", {}).get("symbols", ["AAPL", "MSFT"]))
    if not symbols:
        symbols = ["AAPL"]

    console.rule("[bold cyan]Paper Trading Simulation")
    console.print(Panel.fit(f"Using config: {config}", border_style="cyan"))

    table = Table(title="Synthetic bar stream", show_header=True, header_style="bold magenta")
    table.add_column("Iteration", justify="right")
    table.add_column("Symbol")
    table.add_column("Close", justify="right")
    table.add_column("Timestamp")

    rng = random.Random(1337)
    last_price = 100.0
    now = datetime.utcnow()
    for idx in range(1, max_iterations + 1):
        symbol = symbols[(idx - 1) % len(symbols)]
        delta = rng.uniform(-0.75, 0.75)
        last_price = max(0.01, last_price + delta)
        table.add_row(str(idx), symbol, f"{last_price:.2f}", now.isoformat())
        now = now.replace(microsecond=0)
        if bar_interval > 0:
            time.sleep(bar_interval)

    console.print(table)
    console.print(f"[green]Simulated fill[/green] symbol={symbols[0]} qty=1 price={last_price:.2f}")


@app.command()
def status() -> None:
    """Display environment-derived runtime status information."""

    _load_env()
    paper_mode = os.getenv("ALPACA_PAPER", "true").lower() in {"1", "true", "yes", "on"}
    symbols = os.getenv("SYMBOLS", "AAPL,MSFT,SPY")
    status_text = f"Mode: {'PAPER' if paper_mode else 'LIVE'}\nSymbols: {symbols}"
    console.print(Panel.fit(status_text, title="Gigatrader Status"))


@app.command()
def doctor() -> None:
    """Run a small suite of diagnostics and print the results."""

    _load_env()
    checks: list[tuple[str, bool, str]] = []
    try:
        import alpaca  # type: ignore  # noqa: F401

        checks.append(("alpaca-py import", True, "ok"))
    except Exception as exc:  # pragma: no cover - defensive guard
        checks.append(("alpaca-py import", False, str(exc)))
    for env_name in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        present = bool(os.getenv(env_name))
        checks.append((env_name, present, "set" if present else "missing"))

    table = Table(title="Diagnostics", show_header=True)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for name, ok, detail in checks:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, detail)
    console.print(table)


if __name__ == "__main__":  # pragma: no cover - manual execution only
    app()
