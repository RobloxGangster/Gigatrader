$env:PYTHONPATH = (Resolve-Path .).Path
if (-not $env:GT_API_PORT) { $env:GT_API_PORT = "8000" }
if (-not $env:GT_UI_PORT)  { $env:GT_UI_PORT  = "8501" }
# Default to mock (safe); set MOCK_MODE=false + Alpaca creds for paper
if (-not $env:MOCK_MODE) { $env:MOCK_MODE = "true" }

python -m playwright install chromium
pytest -q -m e2e tests/e2e
