@echo on
setlocal EnableExtensions EnableDelayedExpansion

REM --- Resolve repo root from scripts folder ---
set "SCRIPTS=%~dp0"
pushd "%SCRIPTS%\.." || (echo [FATAL] Failed to cd to repo root & pause & exit /b 1)
set "ROOT=%CD%"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
set "LOG=%ROOT%\logs\setup.log"
echo [INFO] Logging to "%LOG%"
echo [INFO] Start %DATE% %TIME% > "%LOG%"
echo [INFO] ROOT=%ROOT%>>"%LOG%"

REM --- Pick Python (prefer py -3.11) ---
set "PYTHON_EXE="
set "PYTHON_ARGS="
for /F "delims=" %%I in ('where py 2^>NUL') do if not defined PYTHON_EXE (set "PYTHON_EXE=%%~fI" & set "PYTHON_ARGS=-3.11")
if not defined PYTHON_EXE if exist "C:\Windows\py.exe" (set "PYTHON_EXE=C:\Windows\py.exe" & set "PYTHON_ARGS=-3.11")
if not defined PYTHON_EXE for /F "delims=" %%I in ('where python 2^>NUL') do if not defined PYTHON_EXE set "PYTHON_EXE=%%~fI"
if not defined PYTHON_EXE (
  echo [ERROR] Python 3.11+ not found in PATH. >> "%LOG%"
  type "%LOG%" & pause & exit /b 1
)
echo [INFO] Using: "%PYTHON_EXE%" %PYTHON_ARGS% >> "%LOG%"

REM --- 1) venv ---
echo [STEP] venv create/activate
call "%PYTHON_EXE%" %PYTHON_ARGS% -m venv ".venv" >> "%LOG%" 2>&1
if errorlevel 1 (echo [ERROR] venv creation failed & type "%LOG%" & pause & exit /b 1)
call ".venv\Scripts\activate.bat" >> "%LOG%" 2>&1

REM --- 2) ensure pip/pip-tools ---
echo [STEP] upgrade pip + install pip-tools
python -m ensurepip --upgrade >> "%LOG%" 2>&1
python -m pip install --upgrade pip >> "%LOG%" 2>&1
python -m pip install --upgrade pip-tools >> "%LOG%" 2>&1 || (echo [ERROR] pip-tools install failed & type "%LOG%" & pause & exit /b 1)

REM --- 3) lock & install deps (compile if *.in exist; else use existing *.txt) ---
echo [STEP] compile lockfiles (if present)
if exist "requirements-core.in" ".venv\Scripts\pip-compile.exe" -q requirements-core.in -o requirements-core.txt >> "%LOG%" 2>&1
if exist "requirements-dev.in"  ".venv\Scripts\pip-compile.exe" -q requirements-dev.in  -o requirements-dev.txt  >> "%LOG%" 2>&1

echo [STEP] install from lockfiles
if not exist "requirements-core.txt" (echo [ERROR] requirements-core.txt missing & type "%LOG%" & pause & exit /b 1)
pip install -r requirements-core.txt >> "%LOG%" 2>&1 || (echo [ERROR] core install failed & type "%LOG%" & pause & exit /b 1)
if exist "requirements-dev.txt" pip install -r requirements-dev.txt >> "%LOG%" 2>&1

REM --- 4) scaffold .env ---
if not exist ".env" if exist ".env.example" copy /Y ".env.example" ".env" >NUL

REM --- 5) fix local alpaca shadowing ---
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

REM --- 6) probe critical imports (alpaca, uvicorn, streamlit) ---
echo [STEP] import probes
python - << "PY"  >> "%LOG%" 2>&1
import sys
def chk(m):
    try:
        __import__(m); print("[OK] import", m)
    except Exception as e:
        print("[FAIL] import", m, "->", e); sys.exit(3)
for m in ("alpaca.data","uvicorn","streamlit"): chk(m)
print("[OK] probes passed")
PY
if errorlevel 3 (echo [ERROR] import probe failed. See logs\setup.log & type "%LOG%" & pause & exit /b 1)

REM --- 7) readiness check (non-fatal missing keys) ---
python -m cli.main check >> "%LOG%" 2>&1

REM --- 8) start API (separate window, stays open) ---
echo [STEP] starting API on 127.0.0.1:8000
start "gigatrader-api" cmd /k ".venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000"

REM --- 9) wait for API health before launching UI (max ~30s) ---
set "PING_URL=http://127.0.0.1:8000/health"
set /a tries=0
:wait_api
set /a tries+=1
python - << "PY"
import sys, os
import urllib.request
url = os.getenv("PING_URL", "http://127.0.0.1:8000/health")
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        status = response.status
        print(status)
        sys.exit(0 if status == 200 else 2)
except Exception:
    sys.exit(2)
PY
if not errorlevel 1 goto api_ready
if %tries% GEQ 15 (
  echo [WARN] API not responding; launching UI anyway.
  goto start_ui
)
echo [INFO] Waiting for API... (%tries%/15)
timeout /t 2 >NUL
goto wait_api

:api_ready
echo [INFO] API is up.

:start_ui
echo [STEP] starting UI
python -m streamlit run "ui\app.py"
if errorlevel 1 (echo [ERROR] Streamlit failed. See logs\setup.log & type "%LOG%" & pause & exit /b 1)

echo [DONE] Completed %DATE% %TIME% >> "%LOG%"
popd
exit /b 0
