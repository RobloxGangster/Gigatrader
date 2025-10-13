@echo on
setlocal
pushd "%~dp0\.."
call ".venv\Scripts\activate.bat"
".venv\Scripts\streamlit.exe" run "ui\app.py"
pause
