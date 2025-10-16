$env:PYTHONPATH = (Resolve-Path .).Path
# Safe default: mock mode on
if (-not $env:MOCK_MODE) { $env:MOCK_MODE = "true" }
pytest -q tests/unit tests/integration
