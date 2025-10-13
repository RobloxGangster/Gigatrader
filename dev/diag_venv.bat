@echo on
setlocal
cd /d "%~dp0\.."

echo [DIAG] Python via py -3.11
py -3.11 -c "import sys; print(sys.version)" || echo [WARN] py -3.11 not available

echo [DIAG] python on PATH
python -c "import sys; print(sys.version)" || echo [WARN] python not available

echo [DIAG] Activate venv and print versions
call .venv\Scripts\activate.bat || (echo [ERR] activation failed & exit /b 1)
python -V
pip -V
where python
where pip
