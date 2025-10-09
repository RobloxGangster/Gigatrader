@echo off
setlocal enabledelayedexpansion
set "STATUS=0"
set "PUSHED=0"

rem Determine repository root relative to this script.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

if not exist "!REPO_ROOT!\.venv\Scripts\activate.bat" (
    echo [!] Virtual environment not found at !REPO_ROOT!\.venv.
    echo     Run PowerShell: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    goto :cleanup
)

call "!REPO_ROOT!\.venv\Scripts\activate.bat" || goto :on_error

if not exist "!REPO_ROOT!\.env" (
    echo [!] Missing .env file. Copy .env.example to .env and fill in your Alpaca credentials.
    set "STATUS=1"
    goto :cleanup
)

if not exist "!REPO_ROOT!\config.yaml" (
    echo [!] Missing config.yaml. Copy config.example.yaml to config.yaml to continue.
    set "STATUS=1"
    goto :cleanup
)

pushd "!REPO_ROOT!"
set "PUSHED=1"
set "PROFILE=paper"
set "LIVE_TRADING="
set "CONFIG_PATH=!REPO_ROOT!\config.yaml"

rem Prefer the trade console script, fall back to python -m app.cli.
where trade >nul 2>nul
if errorlevel 1 (
    python -m app.cli paper --config "!CONFIG_PATH!"
) else (
    trade paper --config "!CONFIG_PATH!"
)

set "STATUS=!ERRORLEVEL!"
if not "!STATUS!"=="0" (
    echo.
    echo [!] Paper trading exited with code !STATUS!.
    pause
)

:cleanup
if "!PUSHED!"=="1" popd >nul 2>nul
endlocal & exit /b %STATUS%

:on_error
set "STATUS=%ERRORLEVEL%"
echo [!] Failed to activate virtual environment. Exit code %STATUS%.
pause
goto :cleanup

REM Smoke test:
REM   scripts\run_paper.bat
