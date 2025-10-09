@echo off
setlocal enabledelayedexpansion
set REPO_ROOT=%~dp0..
if not exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (echo Run scripts\install.ps1 & exit /b 1)
call "%REPO_ROOT%\.venv\Scripts\activate.bat"
if /I not "%LIVE_TRADING%"=="true" (
    echo Refusing to run live. Set LIVE_TRADING=true then re-run:
    echo   set LIVE_TRADING=true ^&^& scripts\run_live.bat
    exit /b 2
)
set PROFILE=live
where trade >nul 2>&1 && (trade live --config "%REPO_ROOT%\config.yaml") || (python -m app.cli live --config "%REPO_ROOT%\config.yaml")

REM Smoke test:
REM   PowerShell:  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
REM   Then:        scripts\run_paper.bat
REM   Backtest:    scripts\run_backtest.bat --days 2 --universe AAPL,MSFT
