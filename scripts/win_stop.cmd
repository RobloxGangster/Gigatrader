@echo off
setlocal
cd /d %~dp0..
set "PIDFILE=runtime\backend.pid"
if exist "%PIDFILE%" (
  for /f %%p in (%PIDFILE%) do taskkill /PID %%p /F
  del "%PIDFILE%" >NUL 2>&1
  echo [OK] Backend stopped.
) else (
  echo [INFO] No backend pidfile found.
)
REM Attempt to close Streamlit gently
for /f "tokens=2" %%p in ('tasklist ^| findstr /I "streamlit.exe"') do taskkill /PID %%p /T /F
echo [OK] Streamlit stopped (if running).
