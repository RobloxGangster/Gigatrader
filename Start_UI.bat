@echo off
setlocal EnableExtensions
set REPO_ROOT=%~dp0
for %%I in ("%REPO_ROOT%") do set REPO_ROOT=%%~fI
if not exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (
  if exist "%REPO_ROOT%\scripts\one_click_install_and_run.bat" call "%REPO_ROOT%\scripts\one_click_install_and_run.bat"
)
if not exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (
  echo [!] Virtualenv not found; run installer first.
  pause & exit /b 1
)
call "%REPO_ROOT%\.venv\Scripts\activate.bat" || (echo [!] venv missing & pause & exit /b 1)
python -m pip install -U streamlit pandas plotly >NUL
start "Gigatrader UI" cmd /k "cd /d "%REPO_ROOT%" & call .venv\Scripts\activate.bat & streamlit run ui\app.py"
exit /b 0
