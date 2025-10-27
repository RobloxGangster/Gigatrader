"""
Gigatrader backend launcher.

This script is spawned by the Streamlit Control Center.
It is responsible for bringing up the FastAPI backend (uvicorn backend.api:app)
listening on 127.0.0.1:8000. It also logs all startup events and any crash tracebacks
to logs/backend_autostart.log so the UI can display them.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

# uvicorn is our ASGI server
import uvicorn


LOG_DIR = os.path.join("logs")
LOG_PATH = os.path.join(LOG_DIR, "backend_autostart.log")


def _ensure_logdir() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def _log(raw: str) -> None:
    """
    Append a UTC timestamped line to backend_autostart.log and flush immediately.
    We flush every write so Streamlit (running in a different process) can tail
    the file in near real-time.
    """
    _ensure_logdir()
    stamp = datetime.utcnow().isoformat() + "Z"
    line = f"[{stamp}] {raw.rstrip()}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def _load_env() -> None:
    """
    Load .env so Alpaca creds and runtime mode flags are available
    to backend.api at import time. If python-dotenv is missing, we just warn.
    """
    try:
        from dotenv import load_dotenv  # python-dotenv must be in requirements
    except Exception as e:
        _log(f"WARNING: python-dotenv import failed ({e}); continuing anyway")
        return

    try:
        # load_dotenv() will search for .env in cwd / parents
        load_dotenv()
        _log("Loaded .env into process environment")
    except Exception as e:
        _log(f"WARNING: load_dotenv() raised {e!r}; continuing anyway")


def main() -> None:
    _ensure_logdir()
    _log("=== START backend_autostart ===")

    # Helpful sanity dump: which Python is running, CWD, etc.
    _log(f"Python exec: {sys.executable}")
    _log(f"CWD: {os.getcwd()}")

    # load env BEFORE uvicorn tries to import backend.api:app.
    _load_env()

    _log("Attempting to launch uvicorn for backend.api:app on 127.0.0.1:8000 ...")

    try:
        uvicorn.run(
            "backend.api:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_level="info",
        )
    except Exception as e:
        _log("!!! BACKEND CRASHED ON STARTUP !!!")
        _log(f"Exception type: {type(e).__name__}")
        _log(f"Exception str: {e}")
        _log("Traceback begins:")
        tb = traceback.format_exc().splitlines()
        for line in tb:
            _log(line)
        _log("Traceback ends.")
        # re-raise so process exits nonzero (UI will see dead PID eventually)
        raise


if __name__ == "__main__":
    main()
