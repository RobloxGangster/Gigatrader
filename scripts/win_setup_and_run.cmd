@echo on
setlocal EnableExtensions EnableDelayedExpansion
REM Resolve repo root as the parent of scripts folder
set "THIS=%~f0"
set "SCRIPTS=%~dp0"
pushd "%SCRIPTS%\.." || (echo Failed to cd to repo root & pause & exit /b 1)
set "ROOT=%CD%"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
set "LOG=%ROOT%\logs\setup.log"

echo [INFO] Starting setup at %DATE% %TIME% > "%LOG%"
echo [INFO] ROOT=%ROOT% >> "%LOG%"

REM Prefer Python Launcher (py.exe) but fall back to python.exe
set "PYTHON_EXE="
set "PYTHON_ARGS="
for /f "delims=" %%I in ('where py 2^>NUL') do if not defined PYTHON_EXE (
  set "PYTHON_EXE=%%~fI"
  set "PYTHON_ARGS=-3.11"
)
if not defined PYTHON_EXE (
  for /f "delims=" %%I in ('where python 2^>NUL') do if not defined PYTHON_EXE set "PYTHON_EXE=%%~fI"
)
if not defined PYTHON_EXE (
  echo [ERROR] Python 3.11+ not found in PATH. >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)
echo [INFO] Using Python at %PYTHON_EXE% %PYTHON_ARGS% >> "%LOG%"

REM 1) venv
echo [STEP] Creating/using .venv >> "%LOG%"
call "%PYTHON_EXE%" %PYTHON_ARGS% -m venv ".venv" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] venv creation failed. See logs\setup.log
  type "%LOG%"
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat" >> "%LOG%" 2>&1

REM 2) pip + pip-tools
echo [STEP] Upgrading pip and installing pip-tools >> "%LOG%"
python -m pip install --upgrade pip pip-tools >> "%LOG%" 2>&1 || (
  echo [ERROR] pip/pip-tools install failed. >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)

REM 3) compile lockfiles if *.in exist
if exist "requirements-core.in" (
  ".venv\Scripts\pip-compile.exe" -q requirements-core.in -o requirements-core.txt >> "%LOG%" 2>&1 || (
    echo [WARN] pip-compile core failed; continuing with existing lockfile >> "%LOG%"
  )
)
if exist "requirements-dev.in" (
  ".venv\Scripts\pip-compile.exe" -q requirements-dev.in -o requirements-dev.txt >> "%LOG%" 2>&1 || (
    echo [WARN] pip-compile dev failed; continuing with existing lockfile >> "%LOG%"
  )
)

REM 4) install deps
echo [STEP] Installing dependencies >> "%LOG%"
if exist "requirements-core.txt" (
  pip install -r requirements-core.txt >> "%LOG%" 2>&1 || goto :pipfail
) else (
  echo [ERROR] requirements-core.txt not found. >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)
if exist "requirements-dev.txt" (
  pip install -r requirements-dev.txt >> "%LOG%" 2>&1 || echo [WARN] dev deps failed >> "%LOG%"
)

REM 5) ensure .env
if not exist ".env" if exist ".env.example" copy /Y ".env.example" ".env" >NUL

REM 6) fix alpaca shadowing
if not exist "tools" mkdir "tools"
> "tools\fix_shadowing.py" (
  echo from pathlib import Path
  echo ROOT=Path(__file__).resolve().parents[1]
  echo ren=[]
  echo for p in list(ROOT.rglob("alpaca")):
  echo ^    if any(t in p.parts for t in (".venv","venv","site-packages",".git")): continue
  echo ^    if p.name=="alpaca":
  echo ^        np=p.with_name("alpaca_local")
  echo ^        if not np.exists():
  echo ^            p.rename(np); ren.append((p,np))
  echo print("RENAMED:", [f"{a} -> {b}" for a,b in ren])
)
python "tools\fix_shadowing.py" >> "%LOG%" 2>&1

REM 7) readiness (non-fatal in paper)
python -m cli.main check >> "%LOG%" 2>&1

REM 8) start API (kept in its own window, shows uvicorn logs)
start "gigatrader-api" cmd /k ".venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000"
if errorlevel 1 (
  echo [ERROR] Failed to start API. >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)

REM 9) start UI here
".venv\Scripts\streamlit.exe" run "ui\app.py"
if errorlevel 1 (
  echo [ERROR] Streamlit failed. >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)

echo [DONE] Completed at %DATE% %TIME% >> "%LOG%"
popd
exit /b 0

:pipfail
echo [ERROR] pip install failed. See logs\setup.log
type "%LOG%"
pause
exit /b 1
