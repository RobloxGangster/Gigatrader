@echo off
setlocal enableextensions enabledelayedexpansion

REM ===================== 0) Paths, log, flags =====================
cd /d %~dp0..
set "ROOT=%CD%"
set "RUNTIME=%ROOT%\runtime"
set "LOGFILE=%ROOT%\setup.log"
set "VENV_DIR=%ROOT%\.venv"
if not exist "%RUNTIME%" mkdir "%RUNTIME%" >NUL 2>&1

REM window behavior on failure
set "HOLD_ON_FAIL=1"

REM fresh log
if exist "%LOGFILE%" del "%LOGFILE%" >NUL 2>&1
call :log "===== Gigatrader setup started %date% %time% ====="
call :log "ROOT=%ROOT%"

set "FAIL_STEP=bootstrap"
set "LAST_RC=0"

REM ===================== helpers =====================
:ckerr
set "LAST_RC=!ERRORLEVEL!"
if "!LAST_RC!"=="0" exit /b 0
exit /b 1

:log
echo %*
>> "%LOGFILE%" echo %date% %time% %*
exit /b 0

:append_file
REM %~1 -> file to append if exists
if exist "%~1" (
  >> "%LOGFILE%" echo ---------- %~nx1 ----------
  type "%~1" >> "%LOGFILE%"
  >> "%LOGFILE%" echo.
) else (
  >> "%LOGFILE%" echo (missing) %~1
)
exit /b 0

:envdump
> "%RUNTIME%\_env.txt" (
  echo === ENV SNAPSHOT ===
  echo DATE/TIME: %date% %time%
  echo OS: %OS%
  echo ROOT: %ROOT%
  echo VENV_DIR: %VENV_DIR%
  echo USERPROFILE: %USERPROFILE%
  echo PROCESSOR_ARCHITECTURE: %PROCESSOR_ARCHITECTURE%
  echo PY_LAUNCHER: (see _where_py.txt)
  echo PYTHON: (see _where_python.txt)
  echo PATH (first 5):
)
for /f "tokens=1-5 delims=;" %%a in ("%PATH%") do (
  >> "%RUNTIME%\_env.txt" echo   %%a
  >> "%RUNTIME%\_env.txt" echo   %%b
  >> "%RUNTIME%\_env.txt" echo   %%c
  >> "%RUNTIME%\_env.txt" echo   %%d
  >> "%RUNTIME%\_env.txt" echo   %%e
)
exit /b 0

:collect_fail
call :log "[ERR] Failure step=%FAIL_STEP% rc=%LAST_RC%"
call :envdump
call :append_file "%RUNTIME%\_env.txt"
call :append_file "%RUNTIME%\_where_py.txt"
call :append_file "%RUNTIME%\_where_python.txt"
call :append_file "%RUNTIME%\_pyver.txt"
call :append_file "%RUNTIME%\_venv_create.txt"
call :append_file "%RUNTIME%\_pip_upgrade.out"
call :append_file "%RUNTIME%\_pip_upgrade.err"
call :append_file "%RUNTIME%\_pip_core.out"
call :append_file "%RUNTIME%\_pip_core.err"
call :append_file "%RUNTIME%\_pip_dev.out"
call :append_file "%RUNTIME%\_pip_dev.err"
call :append_file "%RUNTIME%\_pipver.txt"
call :append_file "%RUNTIME%\_piplist.txt"
call :append_file "%RUNTIME%\_pytest.txt"
call :append_file "%RUNTIME%\backend.out.log"
call :append_file "%RUNTIME%\backend.err.log"
call :append_file "%RUNTIME%\_health.txt"
call :append_file "%RUNTIME%\streamlit.out.log"
call :append_file "%RUNTIME%\streamlit.err.log"
>> "%LOGFILE%" echo ===== END OF FAILURE REPORT =====
exit /b 0

:fail
call :log "[ERR] Aborted. See %LOGFILE% and raw logs in runtime\\"
call :collect_fail
if "%HOLD_ON_FAIL%"=="1" (
  echo.
  echo [Press any key to close this window...]
  pause >NUL
)
exit /b 1

REM ===================== 1) Discover Python launcher / fallback =====================
set "FAIL_STEP=discover_python"
where py > "%RUNTIME%\_where_py.txt" 2>&1
set "HAVE_PY=1"
for /f "tokens=* delims=" %%X in ('findstr /I /C:"Could not find files" "%RUNTIME%\_where_py.txt"') do set "HAVE_PY="
if not defined HAVE_PY (
  call :log "[WARN] 'py' launcher not found. Trying 'python' from PATH..."
  where python > "%RUNTIME%\_where_python.txt" 2>&1
  set "HAVE_PYTHON=1"
  for /f "tokens=* delims=" %%X in ('findstr /I /C:"Could not find files" "%RUNTIME%\_where_python.txt"') do set "HAVE_PYTHON="
  if not defined HAVE_PYTHON (
    call :log "[ERR] No Python launcher or python.exe found on PATH."
    set "LAST_RC=1"
    goto :fail
  )
)

REM ===================== 2) Create or locate venv =====================
set "FAIL_STEP=create_venv"
set "PY=%VENV_DIR%\Scripts\python.exe"
if not exist "%PY%" (
  if defined HAVE_PY (
    call :log "[INFO] Creating venv with 'py -3.11'..."
    py -3.11 -m venv "%VENV_DIR%" > "%RUNTIME%\_venv_create.txt" 2>&1
    if errorlevel 1 (
      call :log "[WARN] 'py -3.11' failed; trying 'python -m venv'..."
      if defined HAVE_PYTHON (
        python -m venv "%VENV_DIR%" >> "%RUNTIME%\_venv_create.txt" 2>&1
      )
    )
  ) else (
    call :log "[INFO] Creating venv with 'python -m venv'..."
    python -m venv "%VENV_DIR%" > "%RUNTIME%\_venv_create.txt" 2>&1
  )
)
if not exist "%PY%" (
  call :log "[ERR] venv Python not found at %PY%"
  set "LAST_RC=1"
  goto :fail
)

REM ===================== 3) Python / Pip info =====================
set "FAIL_STEP=python_info"
"%PY%" -V > "%RUNTIME%\_pyver.txt" 2>&1
call :append_file "%RUNTIME%\_pyver.txt"

set "PIP_CMD=%PY% -m pip"
%PIP_CMD% --version > "%RUNTIME%\_pipver.txt" 2>&1

REM ===================== 4) Clean stray broken packages =====================
set "FAIL_STEP=clean_site_packages"
for /f "usebackq tokens=*" %%p in (`"%PY%" -c "import site,sys; sp=[p for p in site.getsitepackages() if p.endswith('site-packages')]; print(sp[0] if sp else sys.prefix)"`) do (
  set "SITE=%%p"
)
call :log "[INFO] Cleaning stray '~*' in: %SITE%"
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%SITE%' -Filter '~*' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue" > "%RUNTIME%\_clean.txt" 2>&1

REM ===================== 5) Upgrade tooling + install deps =====================
set "FAIL_STEP=upgrade_pip"
call :log "[INFO] Upgrading pip/setuptools/wheel..."
%PIP_CMD% install --upgrade pip setuptools wheel 1>"%RUNTIME%\_pip_upgrade.out" 2>"%RUNTIME%\_pip_upgrade.err"
call :ckerr || goto :fail

set "FAIL_STEP=install_core_reqs"
call :log "[INFO] Installing requirements-core.txt..."
%PIP_CMD% install -r "%ROOT%\requirements-core.txt" 1>"%RUNTIME%\_pip_core.out" 2>"%RUNTIME%\_pip_core.err"
call :ckerr || goto :fail

set "FAIL_STEP=install_dev_reqs"
call :log "[INFO] Installing requirements-dev.txt..."
%PIP_CMD% install -r "%ROOT%\requirements-dev.txt" 1>"%RUNTIME%\_pip_dev.out" 2>"%RUNTIME%\_pip_dev.err"
call :ckerr || goto :fail

%PIP_CMD% list --format=columns > "%RUNTIME%\_piplist.txt" 2>&1

REM ===================== 6) Tests (non-blocking) =====================
set "FAIL_STEP=pytest"
call :log "[INFO] Running tests (pytest -q)..."
"%PY%" -m pytest -q > "%RUNTIME%\_pytest.txt" 2>&1
set "LAST_RC=!ERRORLEVEL!"
if not "!LAST_RC!"=="0" (
  call :log "[WARN] Tests failed (continuing). rc=!LAST_RC!"
)

REM ===================== 7) Launch backend with logging =====================
set "FAIL_STEP=backend_launch"
call :log "[INFO] Launching backend (uvicorn)..."
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PY%' -ArgumentList '-m uvicorn backend.api:app --host 127.0.0.1 --port 8000' -RedirectStandardOutput '%RUNTIME%\backend.out.log' -RedirectStandardError '%RUNTIME%\backend.err.log' -PassThru; ^
   Set-Content -Path '%RUNTIME%\backend.pid' -Value $p.Id; ^
   Start-Sleep -Seconds 4; ^
   try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing).StatusCode | Out-File -FilePath '%RUNTIME%\_health.txt' -Force } catch { '0' | Out-File -FilePath '%RUNTIME%\_health.txt' -Force }"

for /f %%s in (%RUNTIME%\_health.txt) do set HEALTH=%%s
call :log "[INFO] Backend health status: %HEALTH%"
if not "%HEALTH%"=="200" (
  set "LAST_RC=1"
  goto :fail
)
call :log "[OK] Backend healthy (200)."

REM ===================== 8) Launch Streamlit UI with logging =====================
set "FAIL_STEP=ui_launch"
call :log "[INFO] Launching Streamlit UI..."
powershell -NoProfile -WindowStyle Minimized -Command ^
  "Start-Process -FilePath '%VENV_DIR%\Scripts\streamlit.exe' -ArgumentList 'run','ui\Home.py' -RedirectStandardOutput '%RUNTIME%\streamlit.out.log' -RedirectStandardError '%RUNTIME%\streamlit.err.log'"

call :log "[OK] All set. Backend+UI launched."
call :log "===== Gigatrader setup finished %date% %time% ====="
exit /b 0
