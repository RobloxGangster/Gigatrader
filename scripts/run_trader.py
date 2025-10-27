#!/usr/bin/env python3
"""Launcher that keeps the backend API and orchestrator running together."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv

from scripts.proc_utils import kill_pid_tree

LOG_DIR = Path("logs")
BACKEND_STDOUT = LOG_DIR / "backend.out.log"
BACKEND_STDERR = LOG_DIR / "backend.err.log"
LAUNCHER_ERR = LOG_DIR / "trader_launcher.err.log"
HEALTH_URL = "http://127.0.0.1:8000/health"
POLL_INTERVAL_SEC = 0.5
HEALTH_TIMEOUT_SEC = 10.0


def _ensure_logs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _open_backend_logs() -> tuple[Any, Any]:
    stdout_handle = BACKEND_STDOUT.open("ab", buffering=0)
    stderr_handle = BACKEND_STDERR.open("ab", buffering=0)
    return stdout_handle, stderr_handle


def _open_launcher_log() -> Any:
    return LAUNCHER_ERR.open("a", encoding="utf-8")


def _log(launcher_log: Any, message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    try:
        launcher_log.write(line + "\n")
        launcher_log.flush()
    except Exception:  # pragma: no cover - best effort logging
        pass


def _start_backend(stdout_handle: Any, stderr_handle: Any, launcher_log: Any) -> subprocess.Popen[Any]:
    env = os.environ.copy()
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    _log(launcher_log, "[run_trader] launching uvicorn backend")
    return subprocess.Popen(
        cmd,
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env,
        creationflags=creationflags,
    )


def _wait_for_backend(launcher_log: Any) -> Dict[str, Any] | None:
    deadline = time.time() + HEALTH_TIMEOUT_SEC
    last_error: str | None = None
    while time.time() < deadline:
        try:
            response = requests.get(HEALTH_URL, timeout=1.5)
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}"
            time.sleep(POLL_INTERVAL_SEC)
            continue
        try:
            payload = response.json()
        except ValueError as exc:
            last_error = f"invalid JSON: {exc}"
            time.sleep(POLL_INTERVAL_SEC)
            continue
        return payload if isinstance(payload, dict) else {}
    if last_error:
        _log(launcher_log, f"[run_trader] backend health check failed: {last_error}")
    else:  # pragma: no cover - defensive
        _log(launcher_log, "[run_trader] backend health check failed: unknown error")
    return None


async def _orchestrator_loop(backend_proc: subprocess.Popen[Any], launcher_log: Any) -> None:
    from backend.routers.deps import get_kill_switch, get_orchestrator

    orchestrator = get_orchestrator()
    await orchestrator.start()
    _log(launcher_log, "[run_trader] orchestrator supervisor started")
    try:
        while True:
            if backend_proc.poll() is not None:
                raise RuntimeError(
                    f"uvicorn exited unexpectedly with code {backend_proc.returncode}"
                )
            await asyncio.sleep(POLL_INTERVAL_SEC)
    except asyncio.CancelledError:  # pragma: no cover - cancellation path
        raise
    finally:
        with suppress(Exception):
            get_kill_switch().engage_sync()
        with suppress(Exception):
            await orchestrator.stop()
        _log(launcher_log, "[run_trader] orchestrator supervisor stopped")


def _log_env_snapshot(launcher_log: Any) -> None:
    profile = os.environ.get("PROFILE") or os.environ.get("TRADING_MODE") or "unknown"
    broker = os.environ.get("BROKER") or os.environ.get("TRADING_BROKER") or "unknown"
    mock_mode = os.environ.get("MOCK_MODE") or os.environ.get("MOCK_MARKET") or "false"
    dry_run = os.environ.get("DRY_RUN") or "false"
    message = (
        f"[run_trader] starting orchestrator with PROFILE={profile}, "
        f"BROKER={broker}, MOCK_MODE={mock_mode}, DRY_RUN={dry_run}"
    )
    _log(launcher_log, message)


def _shutdown_backend(proc: subprocess.Popen[Any], launcher_log: Any) -> None:
    if proc.poll() is None:
        _log(launcher_log, "[run_trader] stopping uvicorn backend")
        kill_pid_tree(proc.pid)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _log(launcher_log, "[run_trader] uvicorn did not exit after terminate; killing")
            with suppress(Exception):
                proc.kill()
            with suppress(Exception):
                proc.wait(timeout=5)
    else:
        _log(
            launcher_log,
            f"[run_trader] uvicorn already exited with code {proc.returncode}",
        )


def main() -> int:
    load_dotenv(override=False)
    _ensure_logs()

    with _open_launcher_log() as launcher_log:
        backend_stdout, backend_stderr = _open_backend_logs()
        backend_proc = None
        try:
            backend_proc = _start_backend(backend_stdout, backend_stderr, launcher_log)
            health_payload = _wait_for_backend(launcher_log)
            if health_payload is None:
                _log(
                    launcher_log,
                    "[run_trader] backend failed to start; see backend.err.log",
                )
                if backend_proc is not None:
                    _shutdown_backend(backend_proc, launcher_log)
                return 1

            _log(launcher_log, "[run_trader] backend is reachable and returned health JSON")
            _log_env_snapshot(launcher_log)

            try:
                asyncio.run(_orchestrator_loop(backend_proc, launcher_log))
            except KeyboardInterrupt:
                _log(launcher_log, "[run_trader] KeyboardInterrupt received; shutting down")
                return 0
            except Exception as exc:  # noqa: BLE001 - log traceback for operators
                tb = traceback.format_exc()
                _log(
                    launcher_log,
                    f"[run_trader] orchestrator loop crashed: {exc}\n{tb}",
                )
                return 1
            finally:
                if backend_proc is not None:
                    _shutdown_backend(backend_proc, launcher_log)
        finally:
            with suppress(Exception):
                backend_stdout.close()
            with suppress(Exception):
                backend_stderr.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - manual execution
    raise SystemExit(main())
