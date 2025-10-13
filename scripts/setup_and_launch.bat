@echo on
setlocal EnableExtensions EnableDelayedExpansion

REM === Resolve repo root relative to this script ===
cd /d "%~dp0\.."
set "ROOT=%CD%"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
set "SETUP_LOG=%ROOT%\logs\setup.log"
set "TEST_LOG=%ROOT%\logs\test.log"

echo [INFO] Root: %ROOT% > "%SETUP_LOG%"
echo [INFO] %DATE% %TIME%>> "%SETUP_LOG%"

REM === Find Python (prefer py -3.11) ===
set "PYEXE="
for /F "delims=" %%I in ('where py 2^>NUL') do if not defined PYEXE set "PYEXE=%%~fI"
if not defined PYEXE if exist "C:\Windows\py.exe" set "PYEXE=C:\Windows\py.exe"

set "PYCMD="
if defined PYEXE set "PYCMD=%PYEXE% -3.11"
if not defined PYEXE for /F "delims=" %%I in ('where python 2^>NUL') do if not defined PYCMD set "PYCMD=%%~fI"
if not defined PYCMD (
  echo [FATAL] Python not found. Install Python 3.11 and re-run.>> "%SETUP_LOG%"
  echo [FATAL] Python not found. Install Python 3.11 and re-run.
  pause & exit /b 1
)

REM === Ensure venv exists ===
if not exist ".venv\Scripts\python.exe" (
  echo [STEP] Creating venv with %PYCMD%>> "%SETUP_LOG%"
  call %PYCMD% -m venv .venv>> "%SETUP_LOG%" 2>>&1
  if errorlevel 1 (
    echo [ERROR] venv creation failed. See %SETUP_LOG%
    type "%SETUP_LOG%" & pause & exit /b 1
  )
)

REM === Activate venv ===
call ".venv\Scripts\activate.bat">> "%SETUP_LOG%" 2>>&1
if errorlevel 1 (
  echo [ERROR] venv activate failed. See %SETUP_LOG%
  type "%SETUP_LOG%" & pause & exit /b 1
)

REM === Upgrade pip and install deps ===
echo [STEP] Installing dependencies...>> "%SETUP_LOG%"
python -m pip install --upgrade pip>> "%SETUP_LOG%" 2>>&1
if exist requirements.txt (
  pip install -r requirements.txt>> "%SETUP_LOG%" 2>>&1
) else (
  pip install fastapi uvicorn requests alpaca-py streamlit python-dotenv pytest>> "%SETUP_LOG%" 2>>&1
)

REM === Ensure .env exists (create template if missing) ===
if not exist ".env" (
  echo [WARN] .env not found. Creating template...>> "%SETUP_LOG%"
  > ".env" (
    echo ALPACA_API_KEY_ID=replace_me
    echo ALPACA_API_SECRET_KEY=replace_me
    echo ALPACA_DATA_FEED=iex
    echo SERVICE_PORT=8000
    echo MOCK_MODE=false
    echo API_BASE_URL=http://127.0.0.1:8000
  )
  start notepad ".env"
  echo [INFO] Please fill your Alpaca keys in .env, then re-run this script if tests fail.>> "%SETUP_LOG%"
)

REM === Base env for child windows ===
set "SERVICE_PORT=8000"
set "API_BASE_URL=http://127.0.0.1:8000"
set "MOCK_MODE=false"
set "PYTHONPATH=%ROOT%"

REM === Optional smoke tests (non-fatal) ===
echo [STEP] Running smoke tests... (see %TEST_LOG%)>> "%SETUP_LOG%"
python -m pytest -q> "%TEST_LOG%" 2>>&1
if errorlevel 1 (
  echo [WARN] Tests reported failures. See logs\test.log. Continuing...>> "%SETUP_LOG%"
  echo [WARN] Tests reported failures. See logs\test.log. Continuing...
)

REM === Start backend (new window) ===
echo [STEP] Starting backend on %API_BASE_URL%>> "%SETUP_LOG%"
start "gigatrader-backend" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe backend\app.py"

REM === Start Streamlit UI via wrapper (new window) ===
echo [STEP] Starting UI (Streamlit)>> "%SETUP_LOG%"
start "gigatrader-ui" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe -m streamlit run ui\Home.py"

REM === Give services a few seconds to bind ===
timeout /t 3 /nobreak >nul

REM === Optional diagnostics if first arg is "diag" ===
if /I "%~1"=="diag" (
  echo [STEP] Running active diagnostics (zip)>> "%SETUP_LOG%"
  start "gigatrader-arch-diag" cmd /k ".venv\Scripts\python.exe" dev\arch_diag.py --zip"
  timeout /t 2 /nobreak >nul
  start "" "%ROOT%\diagnostics"
)

echo.
echo [OK] Setup complete.
echo  - Backend:    http://127.0.0.1:8000
echo  - Streamlit:  http://localhost:8501
echo [TIP] To re-run diagnostics later:  .venv\Scripts\python.exe dev\arch_diag.py --zip
echo Logs: %SETUP_LOG%  and  %TEST_LOG%
echo.
exit /b 0
