Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

## Windows Quick Start
1. Open **Command Prompt** (`cmd.exe`) in the repository folder.
2. Run `scripts\windows_setup.cmd`.
   - Creates a Python 3.11 virtual environment, compiles & installs dependencies, and copies `.env` from `.env.example` if needed.
   - Resolves any local `alpaca/` shadowing via `tools\fix_shadowing.py`.
   - Starts the FastAPI backend on http://127.0.0.1:8000 and the Streamlit UI.
3. Populate `.env` with your Alpaca paper credentials. Paper mode is default. Live trading requires setting `LIVE_TRADING=true` and using the **Start Live** button (with confirmation) in the UI.

## Local testing (mirrors CI)
```
pytest -q
```

## Env variables
See `.env.example` for required vars. Paper vs live is controlled by `ALPACA_PAPER=true|false`
and `TRADING_MODE=paper|live` (defaults favour paper).

## Safety
This step only uses paper endpoints by default. Live trading requires explicit env changes in later steps.

Secret Hygiene
--------------
Never commit .env. If accidentally committed, rotate keys and scrub history (e.g., BFG or git-filter-repo), then force-push.
