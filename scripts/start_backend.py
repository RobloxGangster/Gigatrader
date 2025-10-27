"""
Spawn the FastAPI backend (uvicorn backend.api:app) on 127.0.0.1:8000.

This script is launched by the Streamlit UI (Control Center) via subprocess.Popen.

Behavior:
- Writes a startup marker AND any crash tracebacks to logs/backend_autostart.log
- Loads .env so Alpaca credentials and runtime flags are in the environment
- Runs uvicorn in-process and blocks for the backend lifetime
"""

import os
import traceback
import uvicorn
from datetime import datetime

LOG_DIR = os.path.join("logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "backend_autostart.log")


def _log(msg: str) -> None:
    """Append a timestamped line to backend_autostart.log."""
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.utcnow().isoformat()}Z] {msg.rstrip()}\n")


def main() -> None:
    # 1. Load .env so things like ALPACA_API_KEY / SECRET / MODE are available
    try:
        from dotenv import load_dotenv  # python-dotenv
        load_dotenv()
        _log("Loaded .env via python-dotenv")
    except Exception as e:
        _log(f"WARNING: could not load .env ({e}) -- continuing anyway")

    _log("=== START backend_autostart ===")
    _log("Attempting to launch uvicorn backend.api:app on 127.0.0.1:8000 ...")

    try:
        # 2. Run uvicorn inline, blocking. If backend import or startup fails,
        #    it'll raise and we'll handle it below.
        uvicorn.run(
            "backend.api:app",
            host="127.0.0.1",
            port=8000,
            log_level="info",
            reload=False,
        )
    except Exception as e:
        # 3. Capture ANY crash from import/boot/runtime.
        _log("!!! BACKEND CRASHED ON STARTUP !!!")
        _log(f"Exception type: {type(e).__name__}")
        _log(f"Exception str: {e}")
        _log("Traceback follows:")
        tb = traceback.format_exc()
        for line in tb.splitlines():
            _log(line)
        # Re-raise so the process exits nonzero. The Streamlit parent will
        # notice the process died and mark backend as not reachable.
        raise


if __name__ == "__main__":
    main()
