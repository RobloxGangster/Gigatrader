@echo off
setlocal
where py >NUL 2>&1 && (set "PY=py -3.11") || (set "PY=python")

REM 1) venv
%PY% -m venv .venv || exit /b 1
call .venv\Scripts\activate

REM 2) deps
%PY% -m pip install --upgrade pip pip-tools
IF EXIST requirements-core.in (
  pip-compile -q requirements-core.in -o requirements-core.txt
)
IF EXIST requirements-dev.in (
  pip-compile -q requirements-dev.in  -o requirements-dev.txt
)
pip install -r requirements-core.txt
IF EXIST requirements-dev.txt pip install -r requirements-dev.txt

REM 3) env
IF NOT EXIST ".env" IF EXIST ".env.example" copy /Y ".env.example" ".env" >NUL

REM 4) fix alpaca shadowing
IF NOT EXIST tools mkdir tools
%PY% tools\fix_shadowing.py

REM 5) readiness
%PY% -m cli.main check || echo NOTE: missing env keys; continuing for paper mode...

REM 6) start API (port 8000) in new window
start "gigatrader-api" cmd /c ".venv\Scripts\python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000"

REM 7) start UI (Streamlit) here
.venv\Scripts\streamlit run ui\app.py
