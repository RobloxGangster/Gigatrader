@echo on
setlocal EnableExtensions EnableDelayedExpansion

rem --- Resolve repo root from scripts folder ---
cd /d "%~dp0\.."
set "ROOT=%CD%"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
set "LOG=%ROOT%\logs\setup.log"
echo [INFO] Logging to "%LOG%"

echo [INFO] Start %DATE% %TIME% > "%LOG%"
echo [INFO] ROOT=%ROOT% >> "%LOG%"

rem --- Pick Python (prefer py -3.11), fallback to python.exe ---
set "PYTHON_EXE="
set "PYTHON_ARGS="

for /F "delims=" %%I in ('where py 2^>NUL') do if not defined PYTHON_EXE (
  set "PYTHON_EXE=%%~fI"
  set "PYTHON_ARGS=-3.11"
)
if not defined PYTHON_EXE if exist "C:\Windows\py.exe" (
  set "PYTHON_EXE=C:\Windows\py.exe"
  set "PYTHON_ARGS=-3.11"
)
if not defined PYTHON_EXE for /F "delims=" %%I in ('where python 2^>NUL') do (
  if not defined PYTHON_EXE set "PYTHON_EXE=%%~fI"
)

if not defined PYTHON_EXE (
  echo [ERROR] Python 3.11+ not found in PATH. >> "%LOG%"
  type "%LOG%"
  echo Press any key to exit...
  pause >nul
  exit /b 1
)

echo [INFO] Using: "%PYTHON_EXE%" %PYTHON_ARGS% >> "%LOG%"

rem --- 1) venv create/activate ---
echo [STEP] venv create/activate
"%PYTHON_EXE%" %PYTHON_ARGS% -m venv ".venv" 1>>"%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] venv creation failed. Full log:
  type "%LOG%"
  echo Press any key to exit...
  pause >nul
  exit /b 1
)

rem IMPORTANT: do NOT redirect activation; we want to SEE errors
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Failed to activate venv. Full log:
  type "%LOG%"
  echo Press any key to exit...
  pause >nul
  exit /b 1
)

rem sanity check
python -V || ( echo [ERROR] Python not available after activation & echo Press any key... & pause >nul & exit /b 1 )

python -m pip install --upgrade pip 1>>"%LOG%" 2>&1
if exist requirements.txt (
  echo [+] Installing requirements (skip if already satisfied)...
  python -m pip install -r requirements.txt 1>>"%LOG%" 2>&1
)

:menu
echo.
echo ========== Gigatrader ==========
echo [1] Start Backend (FastAPI) on http://127.0.0.1:8000
echo [2] Start UI (Streamlit)
echo [3] Start Paper Runner (headless)
echo [4] Flatten & Halt (kill-switch + close positions)
echo [5] Stop All (best-effort)
echo [A] Active Architecture Diagnostics (zip)
echo [P] Passive Architecture Diagnostics (zip)
echo [D] Diagnostics (venv/backend smoke)
echo [0] Exit
echo.
set /p choice="Select> "

if /I "%choice%"=="1" goto start_backend
if /I "%choice%"=="2" goto start_ui
if /I "%choice%"=="3" goto start_runner
if /I "%choice%"=="4" goto flatten
if /I "%choice%"=="5" goto stop_all
if /I "%choice%"=="A" goto arch_diag_active
if /I "%choice%"=="P" goto arch_diag_passive
if /I "%choice%"=="D" goto diagnostics
if "%choice%"=="0" goto end
goto menu

:start_backend
start "gigatrader-backend" cmd /k python backend\app.py
goto menu

:start_ui
set MOCK_MODE=false
set API_BASE_URL=http://127.0.0.1:8000
start "gigatrader-ui" cmd /k python -m streamlit run ui\Home.py
goto menu

:start_runner
start "gigatrader-runner" cmd /k python -m app.cli run
goto menu

:flatten
echo [+] Engaging kill-switch and attempting flatten...
type nul > .kill_switch
python backend\tools\flatten_all.py
goto menu

:stop_all
for /f "tokens=2 delims==," %%p in ('
  wmic process where "name='cmd.exe' and CommandLine like '%%gigatrader-%%'"
  get ProcessId /value ^| find "="
') do taskkill /PID %%p /F
goto menu

:arch_diag_active
start "gigatrader-arch-diag" cmd /k python dev\arch_diag.py --zip
goto menu

:arch_diag_passive
start "gigatrader-arch-diag-passive" cmd /k python dev\arch_diag.py --no-active --zip
goto menu

:diagnostics
call dev\diag_venv.bat
if exist dev\smoke.py python dev\smoke.py
goto menu

:end
exit /b 0
