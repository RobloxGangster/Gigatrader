$py = (Get-Command py -ErrorAction SilentlyContinue) ? "py -3.11" : "python"
& $py -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pip-tools
if (Test-Path requirements-core.in) { pip-compile -q requirements-core.in -o requirements-core.txt }
if (Test-Path requirements-dev.in)  { pip-compile -q requirements-dev.in  -o requirements-dev.txt }
pip install -r requirements-core.txt
if (Test-Path requirements-dev.txt) { pip install -r requirements-dev.txt }
if (!(Test-Path .env) -and (Test-Path .env.example)) { Copy-Item .env.example .env }
python tools\fix_shadowing.py
python -m cli.main check
Start-Process -FilePath python -ArgumentList "-m","uvicorn","backend.api:app","--host","127.0.0.1","--port","8000"
streamlit run ui\app.py
