$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$policy = Get-ExecutionPolicy
if ($policy -eq 'Restricted') {
    Write-Host "Execution policy is Restricted. Please launch PowerShell with a more permissive policy (e.g. Bypass) and rerun." -ForegroundColor Red
    exit 1
}

$pythonExe = $null
$pythonArgs = @()
try {
    $pyVersion = & py -3.11 -V 2>$null
    if ($LASTEXITCODE -eq 0 -and $pyVersion -match '3\.11') {
        $pythonExe = 'py'
        $pythonArgs = @('-3.11')
    }
} catch {
}

if (-not $pythonExe) {
    try {
        $pyVersion = & python -V 2>$null
        if ($LASTEXITCODE -eq 0) {
            if ($pyVersion -match 'Python (?<maj>\d+)\.(?<min>\d+)') {
                $maj = [int]$Matches['maj']
                $min = [int]$Matches['min']
                if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) {
                    $pythonExe = 'python'
                }
            }
        }
    } catch {
    }
}

if (-not $pythonExe) {
    Write-Host "Python 3.11 is required. Install it from https://www.python.org/downloads/windows/ or enable the 'py -3.11' launcher." -ForegroundColor Red
    exit 1
}

$venvPath = Join-Path $RepoRoot '.venv'
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment at $venvPath" -ForegroundColor Cyan
    & $pythonExe @pythonArgs -m venv $venvPath
}

$activate = Join-Path $venvPath 'Scripts\Activate.ps1'
if (-not (Test-Path $activate)) {
    Write-Host "Virtual environment activation script missing at $activate" -ForegroundColor Red
    exit 1
}
& $activate

$requirementsPath = Join-Path $RepoRoot 'requirements.txt'
if (-not (Test-Path $requirementsPath)) {
    "typer>=0.12`npydantic>=2`npython-dotenv>=1`nrich>=13" | Out-File -FilePath $requirementsPath -Encoding utf8 -Force
}

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r "$requirementsPath"

$srcDir = Join-Path $RepoRoot 'src'
$appDir = Join-Path $srcDir 'app'
if (-not (Test-Path $appDir)) {
    New-Item -ItemType Directory -Path $appDir -Force | Out-Null
}

$initPath = Join-Path $appDir '__init__.py'
if (-not (Test-Path $initPath)) {
    New-Item -ItemType File -Path $initPath -Force | Out-Null
}

$cliPath = Join-Path $appDir 'cli.py'
if (-not (Test-Path $cliPath)) {
    @"
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
"@ | Out-File -FilePath $cliPath -Encoding utf8 -Force
}

$envExample = Join-Path $RepoRoot '.env.example'
$envPath = Join-Path $RepoRoot '.env'
if ((Test-Path $envExample) -and -not (Test-Path $envPath)) {
    Copy-Item $envExample $envPath
}

$configExample = Join-Path $RepoRoot 'config.example.yaml'
$configPath = Join-Path $RepoRoot 'config.yaml'
if ((Test-Path $configExample) -and -not (Test-Path $configPath)) {
    Copy-Item $configExample $configPath
}

python -m pip install -e "$RepoRoot"

Write-Host "Installation complete." -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1) scripts\\run_paper.bat" -ForegroundColor Yellow
Write-Host "  2) scripts\\run_backtest.bat --days 3 --universe AAPL,MSFT" -ForegroundColor Yellow

# Smoke test:
#   PowerShell:  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
#   Then:        scripts\run_paper.bat
#   Backtest:    scripts\run_backtest.bat --days 2 --universe AAPL,MSFT
