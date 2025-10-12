@echo off
setlocal
set "VENV_DIR=.venv"
where py >NUL 2>&1
if %ERRORLEVEL% EQU 0 ( set "PYTHON=py -3.11" ) else ( set "PYTHON=python" )
echo [1/6] Creating venv...
%PYTHON% -m venv "%VENV_DIR%" || goto :fail
set "PY=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"
echo [2/6] Upgrading pip and installing pip-tools...
"%PY%" -m pip install --upgrade pip pip-tools || goto :fail
echo [3/6] Compiling lockfiles...
"%VENV_DIR%\Scripts\pip-compile.exe" -q requirements-core.in -o requirements-core.txt || goto :fail
"%VENV_DIR%\Scripts\pip-compile.exe" -q requirements-dev.in -o requirements-dev.txt || goto :fail
if exist requirements-ml.in "%VENV_DIR%\Scripts\pip-compile.exe" -q requirements-ml.in -o requirements-ml.txt
echo [4/6] Installing dependencies...
"%PIP%" install -r requirements-core.txt -r requirements-dev.txt || goto :fail
if exist requirements-ml.txt "%PIP%" install -r requirements-ml.txt
echo [5/6] Preparing .env...
if not exist ".env" if exist ".env.example" copy /Y ".env.example" ".env" >NUL
if not exist "config.yaml" if exist "config.example.yaml" copy /Y "config.example.yaml" "config.yaml" >NUL
echo [6/6] Readiness check...
"%PY%" -m cli.main check
if %ERRORLEVEL% NEQ 0 echo NOTE: continuing in paper mode with defaults...
echo Launching paper runner...
"%PY%" -m cli.main run
goto :eof
:fail
echo Setup failed. See messages above.
exit /b 1
