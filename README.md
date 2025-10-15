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

