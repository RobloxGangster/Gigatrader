@echo off
setlocal ENABLEDELAYEDEXPANSION

REM === Go to repo root ===
cd /d "%~dp0\.."

REM === Activate venv ===
if not exist .venv\Scripts\activate.bat (
  echo [ERROR] .venv not found. Create it and install deps first.
  exit /b 1
)
call .venv\Scripts\activate.bat

REM === Fail fast for live paper mode if keys missing ===
if /I "%MOCK_MODE%"=="false" (
  if "%ALPACA_KEY_ID%"==""  echo [ERROR] ALPACA_KEY_ID missing & exit /b 1
  if "%ALPACA_SECRET_KEY%"=="" echo [ERROR] ALPACA_SECRET_KEY missing & exit /b 1
  if "%ALPACA_BASE_URL%"=="" echo [ERROR] ALPACA_BASE_URL missing & exit /b 1
)

REM === Pick backend port (PowerShell probe) ===
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
  "$cand=8000..8015; $p=$null; foreach($x in $cand){ try{ $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $x); $l.Start(); $l.Stop(); $p=$x; break } catch{} }; if(-not $p){$p=8000}; [Console]::WriteLine($p)"`) do (
  set "BACKEND_PORT=%%P"
)
echo %BACKEND_PORT%| findstr /r "^[0-9][0-9]*$" >nul || set "BACKEND_PORT=8000"

REM === Pick UI port (PowerShell probe) ===
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
  "$cand=8501..8516; $p=$null; foreach($x in $cand){ try{ $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $x); $l.Start(); $l.Stop(); $p=$x; break } catch{} }; if(-not $p){$p=8501}; [Console]::WriteLine($p)"`) do (
  set "UI_PORT=%%P"
)
echo %UI_PORT%| findstr /r "^[0-9][0-9]*$" >nul || set "UI_PORT=8501"

set "BACKEND_BASE=http://127.0.0.1:%BACKEND_PORT%"

echo [INFO] Using backend %BACKEND_BASE%  (auto-detected)
echo [INFO] Using UI port %UI_PORT%
echo Waiting for backend at %BACKEND_BASE%/health ...

REM === Start backend in a new window ===
start "Gigatrader Backend" cmd /k "uvicorn backend.api:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

REM === Wait for /health on chosen port (max ~40s) ===
for /l %%i in (1,1,40) do (
  powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing %BACKEND_BASE%/health -TimeoutSec 2) > $null; exit 0 } catch { exit 1 }" >nul 2>&1
  if !errorlevel! EQU 0 goto :UI
  timeout /t 1 >nul
)
echo [WARN] Could not confirm backend health; continuing anyway.

:UI
REM === Export BACKEND_BASE for Streamlit (inherited by child window) ===
set "BACKEND_BASE=%BACKEND_BASE%"

REM === Start UI in a new window ===
start "Gigatrader UI" cmd /k "streamlit run ui/Home.py --server.address=127.0.0.1 --server.port=%UI_PORT%"

echo [INFO] Backend: %BACKEND_BASE%
echo [INFO] UI:      http://127.0.0.1:%UI_PORT%
exit /b 0
