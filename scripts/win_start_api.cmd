@echo on
setlocal
pushd "%~dp0\.."
call ".venv\Scripts\activate.bat"
".venv\Scripts\python.exe" -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
pause
