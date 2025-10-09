@echo off
setlocal enabledelayedexpansion
set "STATUS=0"
set "PUSHED=0"

rem Fail closed unless LIVE_TRADING is explicitly confirmed.
set "LIVE_TRADING_FLAG=%LIVE_TRADING%"
if /I not "%LIVE_TRADING_FLAG%"=="true" (
    powershell -NoProfile -Command "Write-Host 'LIVE_TRADING must be set to true to enable live trading.' -ForegroundColor Red"
    echo     Example: set LIVE_TRADING=true ^&^& scripts\run_live.bat
    set "STATUS=1"
    goto :cleanup
)

rem Determine repository root relative to this script.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

if not exist "!REPO_ROOT!\.venv\Scripts\activate.bat" (
    echo [!] Virtual environment not found at !REPO_ROOT!\.venv.
    echo     Run PowerShell: powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    set "STATUS=1"
    goto :cleanup
)

call "!REPO_ROOT!\.venv\Scripts\activate.bat" || goto :on_error

if not exist "!REPO_ROOT!\.env" (
    echo [!] Missing .env file. Live trading requires valid Alpaca credentials.
    set "STATUS=1"
    goto :cleanup
)

if not exist "!REPO_ROOT!\config.yaml" (
    echo [!] Missing config.yaml. Copy config.example.yaml to config.yaml before proceeding.
    set "STATUS=1"
    goto :cleanup
)

pushd "!REPO_ROOT!"
set "PUSHED=1"
set "PROFILE=live"
set "LIVE_TRADING=true"
set "CONFIG_PATH=!REPO_ROOT!\config.yaml"

set "ALPACA_ENDPOINT=%ALPACA_BASE_URL%"
if not defined ALPACA_ENDPOINT set "ALPACA_ENDPOINT=(unknown)"

rem Safety banner prior to execution.
echo ======================================================
echo   Gigatrader LIVE session
echo   PROFILE = !PROFILE!
echo   Alpaca endpoint = !ALPACA_ENDPOINT!
echo   Press Ctrl+C now to abort if this looks wrong.
echo ======================================================

where trade >nul 2>nul
if errorlevel 1 (
    python -m app.cli live --config "!CONFIG_PATH!"
) else (
    trade live --config "!CONFIG_PATH!"
)

set "STATUS=!ERRORLEVEL!"
if not "!STATUS!"=="0" (
    echo.
    echo [!] Live trading exited with code !STATUS!.
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
REM   set LIVE_TRADING=true && scripts\run_live.bat
