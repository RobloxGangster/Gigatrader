Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

## Windows Quick Start
1. Run: `scripts\archive_old_scripts.cmd` (one-time) — moves legacy batch files to `scripts\_legacy\`.
2. Run: `scripts\win_setup_and_run.cmd`
   - Sets up `.venv`, installs dependencies, fixes Alpaca shadowing
   - Starts API (kept open) and then Streamlit UI
3. Edit `.env` with your Alpaca paper keys if not set.
   - `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `APCA_API_BASE_URL=https://paper-api.alpaca.markets`
Troubleshooting: see `logs\setup.log` and the API window for errors.

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
