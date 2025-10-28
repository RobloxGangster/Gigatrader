"""
Gigatrader backend launcher.

This script is spawned by the Streamlit Control Center to boot the FastAPI backend
(uvicorn backend.api:app on 127.0.0.1:8000). It writes detailed, flushed logs to
logs/backend_autostart.log so the UI can debug why the backend may not be
responding at /health.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

import uvicorn  # runtime dependency for serving FastAPI


LOG_DIR = os.path.join("logs")
LOG_PATH = os.path.join(LOG_DIR, "backend_autostart.log")


def _ensure_logdir() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def _log(raw: str) -> None:
    """
    Append `raw` to backend_autostart.log with a UTC timestamp, flush immediately.
    We fsync so a different process (Streamlit) can read live.
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
    Load .env so ALPACA_* creds, mode flags (paper/live), DRY_RUN, etc. are
    available before importing backend.api. If python-dotenv isn't present, log a
    warning but continue.
    """
    try:
        from dotenv import load_dotenv  # python-dotenv must be in requirements
    except Exception as e:
        _log(f"WARNING: python-dotenv import failed ({e}); continuing anyway")
        return

    try:
        loaded = load_dotenv()  # will search for .env automatically
        _log(f"Loaded .env into process environment (loaded={loaded})")
    except Exception as e:
        _log(f"WARNING: load_dotenv() raised {e!r}; continuing anyway")


def _log_runtime_env_snapshot() -> None:
    """
    Dump a minimal snapshot of runtime config so we can tell if we're in paper vs
    live, etc. Redact anything that looks secret.
    """
    keys_of_interest = []
    for k in os.environ.keys():
        # grab broker / mode / alpaca - but don't spam entire environment
        if k.upper().startswith("ALPACA") or "BROKER" in k.upper() or "PAPER" in k.upper() or "DRY" in k.upper():
            keys_of_interest.append(k)

    if not keys_of_interest:
        _log("No interesting runtime env vars (ALPACA_*, *_BROKER*, PAPER, DRY*) found to log")
        return

    _log("Runtime env snapshot:")
    for k in sorted(keys_of_interest):
        v = os.environ.get(k, "")
        redacted = v
        if "SECRET" in k.upper() or "KEY" in k.upper() or "TOKEN" in k.upper():
            if len(v) > 4:
                redacted = v[:2] + "****" + v[-2:]
            else:
                redacted = "****"
        _log(f"  {k} = {redacted}")


def main() -> None:
    _ensure_logdir()

    # Banner header every launch
    _log("=== START backend_autostart ===")

    # Log launcher PID, python, cwd. This helps us correlate with Streamlit.
    _log(f"Launcher PID: {os.getpid()}")
    _log(f"Python exec: {sys.executable}")
    _log(f"CWD: {os.getcwd()}")

    # Pull in .env BEFORE uvicorn imports backend.api:app.
    _load_env()
    _log_runtime_env_snapshot()

    _log("Attempting to launch uvicorn for backend.api:app on 127.0.0.1:8000 ...")

    crashed = False
    crash_tb_lines: list[str] = []
    try:
        # uvicorn.run blocks until the server stops or fails.
        uvicorn.run(
            "backend.api:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_level="info",
        )
    except Exception as e:
        crashed = True
        _log("!!! uvicorn.run() RAISED AN EXCEPTION !!!")
        _log(f"Exception type: {type(e).__name__}")
        _log(f"Exception str: {e}")
        crash_tb_lines = traceback.format_exc().splitlines()
    finally:
        if crashed:
            _log("Traceback begins:")
            for line in crash_tb_lines:
                _log(line)
            _log("Traceback ends.")
        else:
            _log("uvicorn.run() returned (server exited or stopped without throwing).")

        _log("backend_autostart.py exiting now.")


if __name__ == "__main__":
    main()
