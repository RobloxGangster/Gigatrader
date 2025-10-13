@echo off
setlocal enableextensions enabledelayedexpansion
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo [+] Creating virtualenv...
  py -3.11 -m venv .venv || (echo [!] Failed to create venv & exit /b 1)
)
call ".venv\Scripts\activate.bat" || (echo [!] Failed to activate venv & exit /b 1)

python -m pip install --upgrade pip >nul
if exist requirements.txt (
  echo [+] Installing requirements (skip if already satisfied)...
  python -m pip install -r requirements.txt
)

:menu
echo.
echo ========== Gigatrader ==========
echo [1] Start Backend (FastAPI) on http://localhost:8000
echo [2] Start UI (Streamlit)
echo [3] Start Paper Runner (headless)
echo [4] Flatten & Halt (kill-switch + close positions)
echo [5] Stop All (best-effort)
echo [0] Exit
echo.
set /p choice="Select> "

if "%choice%"=="1" goto start_backend
if "%choice%"=="2" goto start_ui
if "%choice%"=="3" goto start_runner
if "%choice%"=="4" goto flatten
if "%choice%"=="5" goto stop_all
if "%choice%"=="0" goto end
goto menu

:start_backend
start "gigatrader-backend" cmd /c ".venv\Scripts\python.exe" backend\app.py
goto menu

:start_ui
set MOCK_MODE=false
set API_BASE_URL=http://localhost:8000
start "gigatrader-ui" cmd /c ".venv\Scripts\python.exe" -m streamlit run ui\Home.py
goto menu

:start_runner
start "gigatrader-runner" cmd /c ".venv\Scripts\python.exe" -m app.cli run
goto menu

:flatten
echo [+] Engaging kill-switch and attempting flatten...
type nul > .kill_switch
".venv\Scripts\python.exe" backend\tools\flatten_all.py
goto menu

:stop_all
for /f "tokens=2 delims==," %%p in ('
  wmic process where "name='cmd.exe' and CommandLine like '%%gigatrader-%%'"
  get ProcessId /value ^| find "="
') do taskkill /PID %%p /F
goto menu

:end
exit /b 0
