Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

## Windows Quick Start
1) Run: scripts\archive_old_scripts.cmd (one-time) — archives legacy launchers to scripts\_legacy\
2) Run: scripts\win_setup_and_run.cmd
   - Creates venv, compiles+installs deps, fixes alpaca shadowing
   - Probes imports; starts API (new window) and Streamlit UI
3) If it fails, check logs\setup.log and the API window for errors.

- Start with `scripts\win_setup_and_run.cmd`.
- If the UI shows “Backend API is not reachable”, close it and double-click the “gigatrader-api” window to verify errors, or run:
  `python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000`

### One-shot setup & launch (Windows)

scripts\win_all_in_one.cmd

This creates/uses .venv, cleans broken packages, installs deps, runs a quick test, launches the backend on 127.0.0.1:8000, and opens the Streamlit UI. To stop:

scripts\win_stop.cmd

If the launcher fails, check **setup.log** at the repo root for a consolidated error report. Raw logs are also under `runtime/`.

## Local testing (mirrors CI)
```
pytest -q
```

## Env variables
See `.env.example` for required vars. Paper vs live is controlled by `ALPACA_PAPER=true|false`
and `TRADING_MODE=paper|live` (defaults favour paper).

## Local launch (backend + orchestrator)
1. Copy `.env.example` to `.env` and fill in your Alpaca paper API keys.
2. Run `python scripts/run_trader.py` to bring up the FastAPI backend and orchestrator.
   - The script writes logs to `logs/backend.*.log` and `logs/orchestrator.*.log`.
3. Start the UI: `streamlit run ui/Home.py`.
4. Open the "Control Center" page and click **Start Trading System** if it is not already running.
5. A green banner should read `PAPER MODE — connected to Alpaca paper.` when keys are valid.
6. The "Recent Activity" section shows live orders/positions pulled from Alpaca paper; a yellow banner
   indicates configuration issues surfaced by `/health`.

## Safety
This step only uses paper endpoints by default. Live trading requires explicit env changes in later steps.

Secret Hygiene
--------------
Never commit .env. If accidentally committed, rotate keys and scrub history (e.g., BFG or git-filter-repo), then force-push.

# Gigatrader — Quick Start (Windows)

> Prereqs: Windows 10+, Python 3.11 (via `py` launcher), Git.  
> Recommended: run from a normal `cmd.exe` (not PowerShell) the first time.

## 1) Clone and prepare
```bat
git clone <your-fork-or-repo-url> Gigatrader
cd Gigatrader
```

Create a `.env` (copy from `.env.example` if present) and fill your Alpaca paper keys:

```env
ALPACA_API_KEY_ID=your_key
ALPACA_API_SECRET_KEY=your_secret
ALPACA_DATA_FEED=iex
SERVICE_PORT=8000
```

## 2) One-shot launcher (installs, tests, launches)
```
scripts\setup_and_launch.bat
```

Creates `.venv` (3.11), upgrades pip, installs `requirements.txt`.

Runs a fast smoke test (`pytest`).

Starts backend on http://127.0.0.1:8000 and Streamlit UI on http://localhost:8501.

Optional: run diagnostics by adding the `diag` argument:

```
scripts\setup_and_launch.bat diag
```

Artifacts/logs:

- `logs\setup.log` (install), `logs\test.log` (pytest), and diagnostics zip in `diagnostics\`.

## 3) Manual launch (if you prefer)
```bat
cd /d E:\GitHub\Gigatrader
.\.venv\Scripts\activate
pip install -r requirements.txt

REM Backend
set SERVICE_PORT=8000
set PYTHONPATH=%CD%
python -m backend.server

REM UI (wrapper auto-detects real app)
set PYTHONPATH=%CD%
python -m streamlit run ui\Home.py
```

### Start Backend Manually
```
.\.venv\Scripts\python.exe -m backend.server
# Health:
curl http://127.0.0.1:8000/health   # -> {"status":"ok"}
```

### Start/Stop runner (paper)
```bat
curl -X POST "http://127.0.0.1:8000/paper/start?preset=balanced"
curl -X POST "http://127.0.0.1:8000/paper/flatten"
curl -X POST "http://127.0.0.1:8000/paper/stop"
```

### Testing orders

`/orders/test` uses a dry-run by default and returns the composed payload plus `client_order_id` without touching the broker. Add `&confirm=true` (or `&execute=true`) to actually place a paper trade. Set `TEST_ORDERS_DEFAULT_DRY_RUN=false` if you need the legacy "submit immediately" behaviour.

### Diagnostics
```bat
python dev\arch_diag.py --zip
start "" diagnostics
```

### Troubleshooting

- **405 on `/paper/start`**: It’s POST-only. Use `curl -X POST ...`.
- **Runner won’t start**: Delete `.kill_switch`, then POST `/paper/start`.
- **UI can’t find entry**: We ship `ui/Home.py` wrapper that locates your real Streamlit file; always run `streamlit run ui\Home.py`.
- **Port 8000 in use**: Set `SERVICE_PORT` in `.env` (and update `API_BASE_URL` for the UI).
- **Missing Alpaca keys**: `/orders` and `/positions` return 400 with a clear message; add keys to `.env`.
- **Sentiment slow or noisy**: It’s cached 5 minutes per symbol. Reduce `hours_back` or `limit` in the query.


## Testing

### Unit + Integration (safe in MOCK_MODE)
```powershell
$env:MOCK_MODE = 'true'
scripts/test_all.ps1

Full UI E2E (Playwright)
# Mock (safe):
$env:MOCK_MODE = 'true'
scripts/test_e2e.ps1

# Paper (requires Alpaca paper creds):
$env:MOCK_MODE = 'false'
$env:ALPACA_API_KEY_ID = '...'
$env:ALPACA_API_SECRET_KEY = '...'
$env:APCA_API_BASE_URL = 'https://paper-api.alpaca.markets'
scripts/test_e2e.ps1
```

Paper-only tests are marked @pytest.mark.paper_only.

Mock-only tests are marked @pytest.mark.mock_only.


---

### One-click test runners (Windows)
- Unit + Integration:
  - Double-click: `scripts\test_all.cmd`
  - Logs: `logs\tests\test_all-YYYYMMDD-HHMMSS.log`
- UI E2E (Playwright):
  - Double-click: `scripts\test_e2e.cmd`
  - Logs: `logs\tests\test_e2e-YYYYMMDD-HHMMSS.log`

Both windows **pause** at the end so you can read errors.  
If venv/dev deps/browsers are missing, the scripts auto-install them.

### Unified test run (one click, one log)
```powershell
# Default (safe): Mock mode
scripts\run_all_tests.cmd

# Paper mode (requires Alpaca paper creds)
$env:MOCK_MODE = 'false'
$env:ALPACA_API_KEY_ID = '...'
$env:ALPACA_API_SECRET_KEY = '...'
$env:APCA_API_BASE_URL = 'https://paper-api.alpaca.markets'
scripts\run_all_tests.cmd
```

Live output streams to the console.

All results written to a single file: logs\tests\test_all_in_one-YYYYMMDD-HHMMSS.log.

Playwright artifacts for failures are under test-results/.


---
