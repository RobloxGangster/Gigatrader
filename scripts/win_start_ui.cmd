@echo on
setlocal
pushd "%~dp0\.."
call ".venv\Scripts\activate.bat"
python -m streamlit run "ui\app.py"
pause
