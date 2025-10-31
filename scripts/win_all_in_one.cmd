@echo off
setlocal ENABLEDELAYEDEXPANSION

cd /d "%~dp0\.."

if not exist .venv\Scripts\activate.bat (
  echo [ERROR] .venv not found. Create it and install deps first.
  exit /b 1
)
call .venv\Scripts\activate.bat

REM Fail fast on live paper if keys missing
if /I "%MOCK_MODE%"=="false" (
  if "%ALPACA_KEY_ID%"==""  echo [ERROR] ALPACA_KEY_ID missing & exit /b 1
  if "%ALPACA_SECRET_KEY%"=="" echo [ERROR] ALPACA_SECRET_KEY missing & exit /b 1
  if "%ALPACA_BASE_URL%"=="" echo [ERROR] ALPACA_BASE_URL missing & exit /b 1
)

start "Gigatrader Backend" cmd /k "uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload"

echo Waiting for backend at http://127.0.0.1:8000/health ...
for /l %%i in (1,1,40) do (
  powershell -Command "try { iwr -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2 ^| Out-Null; exit 0 } catch { exit 1 }"
  if !errorlevel! EQU 0 goto :UI
  timeout /t 1 >nul
)
echo [WARN] Could not confirm backend health; continuing.

:UI
start "Gigatrader UI" cmd /k "streamlit run ui/Home.py --server.address=127.0.0.1 --server.port=8501"

echo [INFO] Backend: http://127.0.0.1:8000
echo [INFO] UI:      http://127.0.0.1:8501
exit /b 0
