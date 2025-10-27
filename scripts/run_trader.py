#!/usr/bin/env python3
"""Unified launcher for the Gigatrader backend and orchestrator.

This script is now the canonical way to bring the entire trading stack online
locally. It starts the FastAPI backend (uvicorn) and the orchestrator loop and
keeps them running together. The Streamlit Control Center "Start Trading
System" button invokes this launcher, but it can also be executed manually for
local testing or automation.

Responsibilities:

* Load environment variables from ``.env`` without clobbering values that are
  already present in the shell environment.
* Spawn the FastAPI backend under ``uvicorn`` and capture stdout/stderr to the
  ``logs/`` directory so diagnostics can be inspected after shutdown.
* Poll the backend ``/health`` endpoint until it returns JSON. The endpoint must
  always respond with HTTP 200 — even degraded states surface an ``ok: false``
  JSON payload rather than an exception.
* Once the backend is reachable, start the orchestrator process.
* Keep both processes alive until interrupted and ensure they are stopped
  cleanly when the user presses Ctrl+C (or when either process exits
  unexpectedly).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv

from core.runtime_flags import get_runtime_flags, parse_bool

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

BACKEND_LOG = LOG_DIR / "backend.out.log"
BACKEND_ERR_LOG = LOG_DIR / "backend.err.log"
ORCH_LOG = LOG_DIR / "orchestrator.out.log"
ORCH_ERR_LOG = LOG_DIR / "orchestrator.err.log"

HEALTH_URL = "http://127.0.0.1:{port}/health"
DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000


def _start_subprocess(cmd: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":  # pragma: no cover - Windows specific
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        cmd,
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env,
        creationflags=creationflags,
    )
    proc._stdout_handle = stdout_handle  # type: ignore[attr-defined]
    proc._stderr_handle = stderr_handle  # type: ignore[attr-defined]
    return proc


def _close_handles(proc: subprocess.Popen) -> None:
    for attr in ("_stdout_handle", "_stderr_handle"):
        handle = getattr(proc, attr, None)
        if handle:
            with suppress(Exception):
                handle.close()


def _poll_health(url: str, *, timeout: float = 10.0) -> Dict[str, Any] | None:
    deadline = time.time() + timeout
    last_error: str | None = None
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=1.5)
        except requests.RequestException as exc:  # pragma: no cover - network variance
            last_error = str(exc)
            time.sleep(0.5)
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return {"ok": False, "error": "invalid json"}
        last_error = f"HTTP {resp.status_code}"
        time.sleep(0.5)
    if last_error:
        print(f"Health check failed: {last_error}")
    return None


def main() -> int:
    load_dotenv(override=False)
    env = os.environ.copy()
    flags = get_runtime_flags()
    backend_port = int(env.get("API_PORT") or DEFAULT_BACKEND_PORT)
    backend_host = env.get("API_HOST", DEFAULT_BACKEND_HOST)
    health_url = HEALTH_URL.format(port=backend_port)

    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api:app",
        "--host",
        backend_host,
        "--port",
        str(backend_port),
    ]

    print("Starting FastAPI backend…")
    backend_proc = _start_subprocess(
        uvicorn_cmd,
        env=env,
        stdout_path=BACKEND_LOG,
        stderr_path=BACKEND_ERR_LOG,
    )

    backend_ready = _poll_health(health_url)
    if backend_ready is None:
        print("Backend did not become healthy. Check logs/backend.err.log")
        backend_proc.terminate()
        with suppress(ProcessLookupError):
            backend_proc.wait(timeout=5)
        _close_handles(backend_proc)
        return 1

    ok_flag = backend_ready.get("ok") if isinstance(backend_ready, dict) else None
    print(f"Backend up ✅ {health_url}")
    if ok_flag is False:
        error_detail = backend_ready.get("error") if isinstance(backend_ready, dict) else None
        if error_detail:
            print(f"Backend reported degraded state: {error_detail}")

    orchestrator_cmd = [sys.executable, "-m", "services.runtime.runner"]
    print("Starting orchestrator…")
    orchestrator_proc = _start_subprocess(
        orchestrator_cmd,
        env=env,
        stdout_path=ORCH_LOG,
        stderr_path=ORCH_ERR_LOG,
    )

    runtime_mode = "mock" if flags.mock_mode else "paper" if flags.paper_trading else "live"
    dry_run = parse_bool(env.get("DRY_RUN"), default=flags.dry_run)
    print(
        "Orchestrator running ✅ (broker=%s, dry_run=%s, mock_mode=%s)"
        % (flags.broker, dry_run, flags.mock_mode)
    )
    if flags.mock_mode:
        print("⚠ MOCK MODE: no live orders will be sent to Alpaca.")
    elif runtime_mode == "paper" and not dry_run:
        print("PAPER MODE — connected to Alpaca paper.")

    try:
        while True:
            time.sleep(1.0)
            if backend_proc.poll() is not None:
                print("Backend process exited unexpectedly. Stopping orchestrator…")
                break
            if orchestrator_proc.poll() is not None:
                print("Orchestrator exited. Stopping backend…")
                break
    except KeyboardInterrupt:
        print("Received Ctrl+C — shutting down…")
    finally:
        for proc in (orchestrator_proc, backend_proc):
            if proc.poll() is None:
                if os.name == "nt":  # pragma: no cover - Windows
                    with suppress(Exception):
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False)
                else:
                    with suppress(Exception):
                        os.kill(proc.pid, signal.SIGTERM)
        with suppress(Exception):
            orchestrator_proc.wait(timeout=10)
        with suppress(Exception):
            backend_proc.wait(timeout=10)
        _close_handles(orchestrator_proc)
        _close_handles(backend_proc)
        print("Shutdown complete.")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
