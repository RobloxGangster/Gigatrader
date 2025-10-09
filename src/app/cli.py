from __future__ import annotations
import os, sys, time, datetime, pathlib, signal
from typing import Optional, List
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from dotenv import load_dotenv

app = typer.Typer(add_completion=False)
console = Console()

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"
FALLBACK_CONFIG = REPO_ROOT / "config.example.yaml"
REPORTS_DIR = REPO_ROOT / "reports"

def _load_env():
    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
        return True
    return False

def _pick_config(explicit: Optional[str]) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit)
        if p.exists():
            return p
        console.print(f"[yellow]Config not found at {p} — continuing with fallback if available.[/yellow]")
    if DEFAULT_CONFIG.exists():
        return DEFAULT_CONFIG
    if FALLBACK_CONFIG.exists():
        console.print(f"[yellow]Using fallback config: {FALLBACK_CONFIG.name}. Create config.yaml to override.[/yellow]")
        return FALLBACK_CONFIG
    console.print("[red]No config file found. Please create config.yaml or keep config.example.yaml.[/red]")
    raise typer.Exit(code=1)

def _warn_missing_keys():
    missing = []
    for k in ("ALPACA_API_KEY","ALPACA_API_SECRET","ALPACA_BASE_URL"):
        if not os.getenv(k):
            missing.append(k)
    if missing:
        console.print(f"[yellow]Missing env keys: {', '.join(missing)}. You can still run paper/backtests, but add them later in .env.[/yellow]")

@app.command()
def paper(config: Optional[str] = typer.Option(None, "--config", help="Path to config.yaml")):
    """Start a stub paper run (dev placeholder)."""
    _load_env()
    _warn_missing_keys()
    cfg = _pick_config(config)
    os.environ["PROFILE"] = "paper"
    os.environ["LIVE_TRADING"] = ""
    console.rule("[bold cyan]Paper Trading (Stub)")
    console.print(Panel.fit(f"Config: {cfg}", title="Using Config", border_style="cyan"))
    console.print("[green]Starting paper loop. Press Ctrl+C to stop.[/green]")

    stop = False
    def _sigint(_sig, _frm):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    i = 0
    while not stop and i < 30:
        console.print(f"[dim]{datetime.datetime.now().strftime('%H:%M:%S')}[/dim] heartbeat: system ok (stub)")
        time.sleep(1.0)
        i += 1
    console.print("[green]Paper run stopped.[/green]")

@app.command()
def backtest(
    config: Optional[str] = typer.Option(None, "--config", help="Path to config.yaml"),
    days: int = typer.Option(5, "--days", min=1, help="Lookback days (stub)"),
    universe: str = typer.Option("AAPL,MSFT", "--universe", help="Comma-separated symbols"),
):
    """Run a stub backtest and emit a tiny HTML report."""
    _load_env()
    cfg = _pick_config(config)
    symbols = [s.strip().upper() for s in universe.split(",") if s.strip()]
    console.rule("[bold magenta]Backtest (Stub)")
    t = Table(title="Params")
    t.add_column("Key"); t.add_column("Value")
    t.add_row("Config", str(cfg))
    t.add_row("Days", str(days))
    t.add_row("Universe", ", ".join(symbols))
    console.print(t)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"{ts}_report.html"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Backtest Report (Stub)</title></head>
<body>
  <h1>Backtest Report (Stub)</h1>
  <p><b>Config:</b> {cfg}</p>
  <p><b>Days:</b> {days}</p>
  <p><b>Universe:</b> {", ".join(symbols)}</p>
  <p>This is a placeholder report to verify the toolchain.</p>
</body></html>
"""
    report_path.write_text(html, encoding="utf-8")
    console.print(f"[green]Report written:[/green] {report_path}")
    console.print("Open it in your browser to confirm output.")
    raise typer.Exit(code=0)

@app.command()
def live(config: Optional[str] = typer.Option(None, "--config", help="Path to config.yaml")):
    """Refuses unless LIVE_TRADING=true."""
    _load_env()
    cfg = _pick_config(config)
    live_ok = os.getenv("LIVE_TRADING", "")
    if live_ok != "true":
        console.print("[red]Refusing to run live. Set LIVE_TRADING=true then re-run.[/red]")
        console.print("Example:  set LIVE_TRADING=true && scripts\\run_live.bat")
        raise typer.Exit(code=2)
    os.environ["PROFILE"] = "live"
    console.rule("[bold red]LIVE Trading (Stub)")
    console.print(Panel.fit(f"Config: {cfg}", title="Using Config", border_style="red"))
    console.print("[yellow]Starting LIVE stub… immediate exit for safety.[/yellow]")
    raise typer.Exit(code=0)

if __name__ == "__main__":
    app()
