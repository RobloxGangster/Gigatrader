Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

## Windows Quick Start
1) Run: scripts\archive_old_scripts.cmd (one-time) — archives legacy launchers to scripts\_legacy\
2) Run: scripts\win_setup_and_run.cmd
   - Creates venv, compiles+installs deps, fixes alpaca shadowing
   - Probes imports; starts API (new window) and Streamlit UI
3) If it fails, check logs\setup.log and the API window for errors.

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
