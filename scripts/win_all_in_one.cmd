@echo off
setlocal enableextensions enabledelayedexpansion

REM ========= 0) Resolve paths =========
cd /d %~dp0..
set "ROOT=%CD%"
set "VENV_DIR=%ROOT%\.venv"
set "PY=%VENV_DIR%\Scripts\python.exe"
set "PIP_CMD=%PY% -m pip"
set "RUNTIME=%ROOT%\runtime"
if not exist "%RUNTIME%" mkdir "%RUNTIME%"

echo [INFO] ROOT=%ROOT%

REM ========= 1) Ensure venv (3.11) =========
if not exist "%PY%" (
  echo [INFO] Creating venv...
  py -3.11 -m venv "%VENV_DIR%" || goto :fail
)
echo [INFO] Python: "%PY%"
"%PY%" -V || goto :fail

REM ========= 2) Clean stray broken packages in site-packages =========
for /f "usebackq tokens=*" %%p in (`"%PY%" -c "import site; print([p for p in site.getsitepackages() if p.endswith('site-packages')][0])"`) do (
  set "SITE=%%p"
)
echo [INFO] Cleaning stray '~*' in %SITE%
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%SITE%' -Filter '~*' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"

REM ========= 3) Upgrade tooling + install deps =========
echo [INFO] Upgrading pip/setuptools/wheel...
%PIP_CMD% install --upgrade pip setuptools wheel || goto :fail
echo [INFO] Installing requirements-core.txt...
%PIP_CMD% install -r "%ROOT%\requirements-core.txt" || goto :fail
echo [INFO] Installing requirements-dev.txt...
%PIP_CMD% install -r "%ROOT%\requirements-dev.txt" || goto :fail

REM ========= 4) Quick sanity tests =========
echo [INFO] Running tests (pytest -q)...
"%PY%" -m pytest -q > "%RUNTIME%\_pytest.txt"
if errorlevel 1 (
  echo [WARN] Tests failed (see runtime\_pytest.txt). Continuing anyway...
)

REM ========= 5) Launch backend (uvicorn) =========
echo [INFO] Launching backend...
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PY%' -ArgumentList '-m uvicorn backend.api:app --host 127.0.0.1 --port 8000' -PassThru; ^
   Set-Content -Path '%RUNTIME%\backend.pid' -Value $p.Id; ^
   Start-Sleep -Seconds 3; ^
   try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing).StatusCode | Out-File -FilePath '%RUNTIME%\_health.txt' -Force } catch { '0' | Out-File -FilePath '%RUNTIME%\_health.txt' -Force }"

for /f %%s in (%RUNTIME%\_health.txt) do set HEALTH=%%s
if not "%HEALTH%"=="200" (
  echo [ERR] Backend health check failed (status %HEALTH%).
  goto :fail
)
echo [OK] Backend healthy (200).

REM ========= 6) Launch Streamlit UI (Home) =========
echo [INFO] Launching Streamlit UI (minimized window)...
powershell -NoProfile -WindowStyle Minimized -Command ^
  "Start-Process -FilePath '%VENV_DIR%\Scripts\streamlit.exe' -ArgumentList 'run','ui\Home.py'"

echo [OK] All set. Backend+UI launched.
exit /b 0

:fail
echo [ERR] Aborted. Check logs under %RUNTIME%.
exit /b 1
