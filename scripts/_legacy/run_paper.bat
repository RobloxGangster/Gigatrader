@echo off
setlocal enabledelayedexpansion
set REPO_ROOT=%~dp0..
if not exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (echo Run scripts\install.ps1 & exit /b 1)
call "%REPO_ROOT%\.venv\Scripts\activate.bat"
if not exist "%REPO_ROOT%\.env" echo Missing .env (a copy is .env.example) & exit /b 1
if not exist "%REPO_ROOT%\config.yaml" if not exist "%REPO_ROOT%\config.example.yaml" echo Missing config files & exit /b 1
set PROFILE=paper
set LIVE_TRADING=
where trade >nul 2>&1 && (trade paper --config "%REPO_ROOT%\config.yaml") || (python -m app.cli paper --config "%REPO_ROOT%\config.yaml")
if errorlevel 1 echo Failed with code %ERRORLEVEL% & pause

REM Smoke test:
REM   PowerShell:  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
REM   Then:        scripts\run_paper.bat
REM   Backtest:    scripts\run_backtest.bat --days 2 --universe AAPL,MSFT
