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
    set "STATUS=1"
    goto :cleanup
)

call "!REPO_ROOT!\.venv\Scripts\activate.bat" || goto :on_error

if not exist "!REPO_ROOT!\.env" (
    echo [!] Missing .env file. Copy .env.example to .env and fill in credentials for Alpaca.
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
set "DEFAULT_CONFIG=!REPO_ROOT!\config.yaml"
set "USER_ARGS=%*"
set "CLI_ARGS=backtest"
set "HTML_LINE="

if not defined USER_ARGS (
    set "CLI_ARGS=!CLI_ARGS! --config \"!DEFAULT_CONFIG!\""
) else (
    set "SEARCH=!USER_ARGS:--config=!"
    if /I "!SEARCH!"=="!USER_ARGS!" (
        set "CLI_ARGS=!CLI_ARGS! --config \"!DEFAULT_CONFIG!\" !USER_ARGS!"
    ) else (
        set "CLI_ARGS=!CLI_ARGS! !USER_ARGS!"
    )
)

set "OUTPUT_FILE=%TEMP%\gigatrader_backtest_!RANDOM!!RANDOM!.log"
if exist "!OUTPUT_FILE!" del "!OUTPUT_FILE!"

where trade >nul 2>nul
if errorlevel 1 (
    python -m app.cli !CLI_ARGS! 1>"!OUTPUT_FILE!" 2>&1
) else (
    trade !CLI_ARGS! 1>"!OUTPUT_FILE!" 2>&1
)
set "STATUS=!ERRORLEVEL!"

type "!OUTPUT_FILE!"

if "!STATUS!"=="0" (
    for /f "usebackq delims=" %%R in (`findstr /R /I ".html" "!OUTPUT_FILE!"`) do (
        if not defined HTML_LINE set "HTML_LINE=%%R"
    )
    if defined HTML_LINE (
        echo.
        echo [i] Backtest report reference detected:
        echo     !HTML_LINE!
    )
) else (
    echo.
    echo [!] Backtest command exited with code !STATUS!.
    pause
)

del "!OUTPUT_FILE!" >nul 2>nul

:cleanup
if "!PUSHED!"=="1" popd >nul 2>nul
endlocal & exit /b %STATUS%

:on_error
set "STATUS=%ERRORLEVEL%"
echo [!] Failed to activate virtual environment. Exit code %STATUS%.
pause
goto :cleanup

REM Smoke test:
REM   scripts\run_backtest.bat --days 5
