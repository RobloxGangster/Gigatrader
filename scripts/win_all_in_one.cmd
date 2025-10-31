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

REM === Pick a backend port that we are ALLOWED to bind (handles WinError 10013) ===
for /f "delims=" %%P in ('powershell -NoProfile -Command ^
  "$cand=8000..8015; foreach($p in $cand){ try{ $l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse(''127.0.0.1''),$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch{} }"') do (
  set BACKEND_PORT=%%P
)
if "%BACKEND_PORT%"=="" set BACKEND_PORT=8000

REM === Pick a UI port similarly ===
for /f "delims=" %%P in ('powershell -NoProfile -Command ^
  "$cand=8501..8516; foreach($p in $cand){ try{ $l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse(''127.0.0.1''),$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch{} }"') do (
  set UI_PORT=%%P
)
if "%UI_PORT%"=="" set UI_PORT=8501

set BACKEND_BASE=http://127.0.0.1:%BACKEND_PORT%

echo [INFO] Using backend %BACKEND_BASE%  (auto-detected)
echo [INFO] Using UI port %UI_PORT%

REM === Start backend in a new window ===
start "Gigatrader Backend" cmd /k "uvicorn backend.api:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

REM === Wait for /health on chosen port (max ~40s) ===
echo Waiting for backend at %BACKEND_BASE%/health ...
for /l %%i in (1,1,40) do (
  powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing %BACKEND_BASE%/health -TimeoutSec 2) > $null; exit 0 } catch { exit 1 }"
  if !errorlevel! EQU 0 goto :UI
  timeout /t 1 >nul
)
echo [WARN] Could not confirm backend health; continuing anyway.

:UI
REM === Export BACKEND_BASE for Streamlit (same window inheritance) ===
set BACKEND_BASE=%BACKEND_BASE%

REM === Start UI in a new window (reads BACKEND_BASE) ===
start "Gigatrader UI" cmd /k "streamlit run ui/Home.py --server.address=127.0.0.1 --server.port=%UI_PORT%"

echo [INFO] Backend: %BACKEND_BASE%
echo [INFO] UI:      http://127.0.0.1:%UI_PORT%
exit /b 0
