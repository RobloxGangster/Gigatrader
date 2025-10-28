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
import time
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = Path(sys.executable).resolve()
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

AUTOSTART_LOG = LOG_DIR / "backend_autostart.log"
BACKEND_OUT_LOG = LOG_DIR / "backend.out.log"
BACKEND_ERR_LOG = LOG_DIR / "backend.err.log"
PID_FILE = LOG_DIR / "backend.pid"
EXIT_FILE = LOG_DIR / "backend.exitcode"

API_MODULE = "backend.api:app"
HOST = "127.0.0.1"
PORT = "8000"


def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(line: str) -> None:
    with AUTOSTART_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{_ts()}] {line}\n")
        f.flush()
        os.fsync(f.fileno())


def main() -> None:
    log("=== backend_autostart begin ===")
    log(f"python exe: {VENV_PY}")
    log(f"cwd: {ROOT}")
    log(f"Attempting to launch uvicorn for {API_MODULE} on {HOST}:{PORT} ...")

    if PID_FILE.exists():
        PID_FILE.unlink()
    if EXIT_FILE.exists():
        EXIT_FILE.unlink()

    sep = f"\n----- NEW LAUNCH {_ts()} -----\n"

    with BACKEND_OUT_LOG.open("a", buffering=1, encoding="utf-8") as out_fh, BACKEND_ERR_LOG.open(
        "a", buffering=1, encoding="utf-8"
    ) as err_fh:
        out_fh.write(sep)
        err_fh.write(sep)
        out_fh.flush()
        err_fh.flush()

        cmd = [
            str(VENV_PY),
            "-m",
            "uvicorn",
            API_MODULE,
            "--host",
            HOST,
            "--port",
            PORT,
            "--log-level",
            "info",
        ]

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                env=os.environ.copy(),
                stdout=out_fh,
                stderr=err_fh,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as e:  # noqa: BLE001 - best effort logging
            log(f"FATAL: could not spawn uvicorn: {e!r}")
            err_fh.write(f"FATAL: could not spawn uvicorn: {e!r}\n")
            err_fh.flush()
            return

        with PID_FILE.open("w", encoding="utf-8") as f:
            f.write(str(proc.pid))
        log(f"Spawned uvicorn PID={proc.pid}")

        time.sleep(1.5)

        retcode = proc.poll()
        if retcode is None:
            log(f"PID {proc.pid} appears alive after grace period.")
            return

        with EXIT_FILE.open("w", encoding="utf-8") as f:
            f.write(str(retcode))
        log(f"PID {proc.pid} exited early with code {retcode}")
        out_fh.flush()
        err_fh.flush()


if __name__ == "__main__":
    main()
