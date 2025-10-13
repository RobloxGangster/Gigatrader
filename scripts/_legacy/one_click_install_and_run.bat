@echo off
setlocal EnableExtensions
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set REPO_ROOT=%%~fI

set "PYTHON_CMD="
for %%C in ("py -3.11" python3 python) do (
  call %%~C -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >NUL 2>&1
  if not errorlevel 1 (
    set "PYTHON_CMD=%%~C"
    goto :found_python
  )
)

echo [!] Python 3.11 not found. Install Python 3.11 and retry.
pause
exit /b 1

:found_python
echo [+] Using %PYTHON_CMD%
if not exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
  echo [+] Creating virtual environment...
  call %PYTHON_CMD% -m venv "%REPO_ROOT%\.venv"
)
if not exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (
  echo [!] Virtualenv activation script missing.
  pause
  exit /b 1
)
call "%REPO_ROOT%\.venv\Scripts\activate.bat" || (
  echo [!] Failed to activate virtualenv.
  pause
  exit /b 1
)
echo [+] Upgrading pip tooling...
python -m pip install -U pip setuptools wheel
if exist "%REPO_ROOT%\requirements.txt" (
  echo [+] Installing requirements...
  python -m pip install -r "%REPO_ROOT%\requirements.txt"
)
if exist "%REPO_ROOT%\pyproject.toml" (
  echo [+] Installing gigatrader package (editable)...
  python -m pip install -e "%REPO_ROOT%"
)
if not exist "%REPO_ROOT%\.env" (
  (
    echo # Gigatrader environment
    echo ALPACA_API_KEY=
    echo ALPACA_API_SECRET=
    echo LIVE_TRADING=
  )>"%REPO_ROOT%\.env"
)
if not exist "%REPO_ROOT%\config.yaml" (
  if exist "%REPO_ROOT%\config.example.yaml" (
    copy "%REPO_ROOT%\config.example.yaml" "%REPO_ROOT%\config.yaml" >NUL
  ) else (
    echo profile: paper>"%REPO_ROOT%\config.yaml"
  )
)
start "Gigatrader Paper" cmd /k "cd /d "%REPO_ROOT%" & call .venv\Scripts\activate.bat & (where trade >NUL 2^>^&1 && trade paper --config config.yaml || python -m app.cli paper --config config.yaml)"
exit /b 0
