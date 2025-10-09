"""Typer CLI entrypoint."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from backtest.engine import BacktestConfig, BacktestEngine
from core.config import load_config
from core.kill_switch import KillSwitch

app = typer.Typer(help="Gigatrader trading CLI")


@app.command()
def backtest(config: Path = typer.Option(..., exists=True)) -> None:
    """Run backtest with the provided config."""

    cfg = load_config(config)
    engine = BacktestEngine([], BacktestConfig())
    asyncio.run(engine.run([]))
    typer.echo(f"Backtest completed for profile {cfg.profile}")


@app.command()
def paper(
    config: Path = typer.Option(..., exists=True),
    risk_profile: str = typer.Option("safe", help="Risk preset override"),
) -> None:
    """Start paper trading run."""

    cfg = load_config(config)
    typer.echo(f"Starting paper run with risk profile {risk_profile or cfg.risk_profile}")
    # TODO: spin up orchestrator


@app.command()
def live(config: Path = typer.Option(..., exists=True)) -> None:
    """Start live trading run (requires LIVE_TRADING flag)."""

    cfg = load_config(config)
    typer.echo(f"Live run requested for profile {cfg.profile}")


@app.command()
def report(run_id: str = typer.Option(...)) -> None:
    """Generate report for run identifier."""

    typer.echo(f"Report generation for run {run_id} is not yet implemented")


@app.command()
def halt() -> None:
    """Engage the global kill switch."""

    kill = KillSwitch()
    asyncio.run(kill.engage())
    typer.echo("Kill switch engaged")


if __name__ == "__main__":
    app()
