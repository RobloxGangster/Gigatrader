@echo on
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0\.."
set "ROOT=%CD%"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"

if not exist ".venv\Scripts\python.exe" (
  echo [+] Creating venv with py -3.11
  C:\Windows\py.exe -3.11 -m venv .venv || (echo [!] venv create failed & pause & exit /b 1)
)
call ".venv\Scripts\activate.bat" || (echo [!] Failed to activate venv & pause & exit /b 1)

python -m pip install --upgrade pip >nul 2>&1

set SERVICE_PORT=8000
set API_BASE_URL=http://127.0.0.1:8000
set MOCK_MODE=false
set PYTHONPATH=%ROOT%

:menu
echo.
echo ========== Gigatrader ==========
echo [1] Start Backend (FastAPI) on %API_BASE_URL%
echo [2] Start UI (Streamlit - auto detect)
echo [3] Start Paper Runner (headless)
echo [4] Flatten & Halt (kill-switch + close positions)
echo [5] Stop All (best-effort)
echo [A] Active Architecture Diagnostics (zip)
echo [P] Passive Architecture Diagnostics (zip)
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
if "%choice%"=="0" goto end
goto menu

:start_backend
start "gigatrader-backend" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe -m backend.server"
goto menu

:start_ui
rem Always run the wrapper; it finds the real entry and executes it
start "gigatrader-ui" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe" -m streamlit run ui\Home.py
goto menu

:start_runner
start "gigatrader-runner" cmd /k "set PYTHONPATH=%ROOT%&& .venv\Scripts\python.exe -m app.cli run"
goto menu

:flatten
echo [+] Engaging kill-switch and attempting flatten...
type nul > .kill_switch
.venv\Scripts\python.exe backend\tools\flatten_all.py
goto menu

:stop_all
for /f "tokens=2 delims==," %%p in ('
  wmic process where "name='cmd.exe' and CommandLine like '%%gigatrader-%%'"
  get ProcessId /value ^| find "="
') do taskkill /PID %%p /F
goto menu

:arch_diag_active
start "gigatrader-arch-diag" cmd /k ".venv\Scripts\python.exe" dev\arch_diag.py --zip
goto menu

:arch_diag_passive
start "gigatrader-arch-diag-passive" cmd /k ".venv\Scripts\python.exe" dev\arch_diag.py --no-active --zip
goto menu

:end
exit /b 0
