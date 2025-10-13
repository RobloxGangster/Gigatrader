@echo on
setlocal EnableExtensions EnableDelayedExpansion

REM --- Provide simple tee helper using PowerShell for logging ---
set "TEE_HELPER=%TEMP%\tee.cmd"
if not exist "%TEE_HELPER%" (
  >"%TEE_HELPER%" (
    echo @echo off
    echo setlocal EnableExtensions EnableDelayedExpansion
    echo if /I "%%~1"=="-a" (
    echo   set "TARGET=%%~2"
    echo   set "APPEND=1"
    echo ) else (
    echo   set "TARGET=%%~1"
    echo   set "APPEND="
    echo )
    echo if not defined TARGET exit /b 0
    echo if not defined APPEND ( ^>"%%TARGET%%" type nul )
    echo powershell -NoProfile -Command "$input | Tee-Object -FilePath '%%TARGET%%' -Append"
    echo endlocal
  )
)
set "PATH=%TEMP%;%PATH%"

REM --- Resolve repo root ---
cd /d "%~dp0\.."
set "ROOT=%CD%"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
set "SETUP_LOG=%ROOT%\logs\setup.log"
set "TEST_LOG=%ROOT%\logs\test.log"

echo [INFO] Root: %ROOT% > "%SETUP_LOG%"
echo [INFO] %DATE% %TIME% >> "%SETUP_LOG%"

REM --- Pick Python 3.11 via py launcher (fallback to python) ---
set "PYEXE="
for /F "delims=" %%I in ('where py 2^>NUL') do if not defined PYEXE set "PYEXE=%%~fI"
if not defined PYEXE if exist "C:\Windows\py.exe" set "PYEXE=C:\Windows\py.exe"
if defined PYEXE (
  set "PYCMD="%PYEXE%" -3.11"
) else (
  for /F "delims=" %%I in ('where python 2^>NUL') do if not defined PYEXE set "PYEXE=%%~fI"
  if defined PYEXE set "PYCMD="%PYEXE%""
)
if not defined PYEXE (
  echo [FATAL] Python not found. Install Python 3.11 and re-run. | tee -a "%SETUP_LOG%"
  pause & exit /b 1
)

REM --- Ensure venv ---
if not exist ".venv\Scripts\python.exe" (
  echo [STEP] Creating venv with %PYCMD% | tee -a "%SETUP_LOG%"
  call %PYCMD% -m venv .venv >> "%SETUP_LOG%" 2>&1 || (echo [ERROR] venv failed & type "%SETUP_LOG%" & pause & exit /b 1)
)

call ".venv\Scripts\activate.bat" >> "%SETUP_LOG%" 2>&1 || (echo [ERROR] venv activate failed & type "%SETUP_LOG%" & pause & exit /b 1)

REM --- Upgrade pip and install deps ---
echo [STEP] Installing dependencies... | tee -a "%SETUP_LOG%"
python -m pip install --upgrade pip >> "%SETUP_LOG%" 2>&1
if exist requirements.txt (
  pip install -r requirements.txt >> "%SETUP_LOG%" 2>&1
) else (
  pip install fastapi uvicorn requests alpaca-py streamlit python-dotenv pytest >> "%SETUP_LOG%" 2>&1
)

REM --- Ensure .env exists (create template if missing) ---
if not exist ".env" (
  echo [WARN] .env not found. Creating template... | tee -a "%SETUP_LOG%"
  > ".env" (
    echo ALPACA_API_KEY_ID=replace_me
    echo ALPACA_API_SECRET_KEY=replace_me
    echo ALPACA_DATA_FEED=iex
    echo SERVICE_PORT=8000
    echo MOCK_MODE=false
    echo API_BASE_URL=http://127.0.0.1:8000
  )
  start notepad ".env"
  echo [INFO] Please fill your Alpaca keys in .env, then re-run this script if tests fail. | tee -a "%SETUP_LOG%"
)

REM --- Basic env for child windows ---
set SERVICE_PORT=8000
set API_BASE_URL=http://127.0.0.1:8000
set MOCK_MODE=false
set PYTHONPATH=%ROOT%

REM --- Run smoke tests (non-fatal but recommended) ---
echo [STEP] Running smoke tests... (see %TEST_LOG%) | tee -a "%SETUP_LOG%"
python -m pytest -q > "%TEST_LOG%" 2>&1
if errorlevel 1 (
  echo [WARN] Tests reported failures. See logs\test.log. Continuing anyway... | tee -a "%SETUP_LOG%"
)

REM --- Start backend (new window) ---
echo [STEP] Starting backend on %API_BASE_URL% | tee -a "%SETUP_LOG%"
start "gigatrader-backend" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe backend\app.py"

REM --- Start Streamlit UI via wrapper (new window) ---
echo [STEP] Starting UI (Streamlit) | tee -a "%SETUP_LOG%"
start "gigatrader-ui" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe -m streamlit run ui\Home.py"

REM --- Small delay to let services bind ---
timeout /t 3 /nobreak >nul

REM --- Optional: run diagnostics if first arg is "diag" ---
if /I "%~1"=="diag" (
  echo [STEP] Running active diagnostics (zip)... | tee -a "%SETUP_LOG%"
  start "gigatrader-arch-diag" cmd /k ".venv\Scripts\python.exe dev\arch_diag.py --zip"
  timeout /t 2 /nobreak >nul
  if not exist "%ROOT%\diagnostics" mkdir "%ROOT%\diagnostics"
  start "" "%ROOT%\diagnostics"
)

echo.
echo [OK] Setup complete. Backend at http://127.0.0.1:8000  UI at http://localhost:8501
echo [TIP] To (re)run diagnostics later:  python dev\arch_diag.py --zip
echo.
exit /b 0

:tee
REM Placeholder (compatibility)
