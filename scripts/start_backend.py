"""
scripts/start_backend.py

Purpose:
- Clean up any stale uvicorn/FastAPI process still holding port 8000.
- Launch the backend API (uvicorn backend.api:app --host 127.0.0.1 --port 8000).
- Stream stdout/stderr into logs/backend.out.log and logs/backend.err.log.
- Write PID to logs/backend.pid and (if it crashes immediately) an exit code to logs/backend.exitcode.
- Emit human-readable status lines to logs/backend_autostart.log so the UI can render them.

This script is called by the Streamlit Control Center "Start Trading System" button.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = Path(sys.executable).resolve()
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

AUTOSTART_LOG   = LOG_DIR / "backend_autostart.log"
BACKEND_OUT_LOG = LOG_DIR / "backend.out.log"
BACKEND_ERR_LOG = LOG_DIR / "backend.err.log"
PID_FILE        = LOG_DIR / "backend.pid"
EXIT_FILE       = LOG_DIR / "backend.exitcode"
PORT_HOLDER_LOG = LOG_DIR / "backend.portdebug.log"  # optional info for who owned the port

API_MODULE = "backend.api:app"
HOST = "127.0.0.1"
PORT = 8000

def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def _log(line: str) -> None:
    with AUTOSTART_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{_ts()}] {line}\n")

def _note_port_holder(holder_info: str) -> None:
    with PORT_HOLDER_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{_ts()}] {holder_info}\n")

def _ensure_port_free(host: str, port: int) -> None:
    """
    Guarantee that (host, port) is free before we spawn uvicorn.
    1. Try psutil to find any listener on host:port, kill it.
    2. If psutil didn't run or found nothing, fall back to Windows netstat+taskkill.
    3. Log *everything* we discover to backend.portdebug.log so the UI can display it.
    """
    offenders = []

    # Try psutil first
    try:
        import psutil
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            try:
                conns = proc.connections(kind="inet")
            except Exception:
                continue
            for c in conns:
                # We only care about LISTEN sockets that match (host, port)
                if (
                    c.laddr
                    and len(c.laddr) == 2
                    and c.laddr[0] == host
                    and c.laddr[1] == port
                    and getattr(c, "status", None) == psutil.CONN_LISTEN
                ):
                    offenders.append((proc.pid, proc.info.get("name", "?"), "psutil"))
                    break
    except Exception as e:
        _log(f"[CLEANUP] psutil scan failed: {e!r}")
        _note_port_holder(f"[CLEANUP] psutil scan failed: {e!r}")

    # Fallback using netstat if we still don't have offenders
    if not offenders:
        try:
            import subprocess, re
            cmd = ["netstat", "-ano"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                # Look for a LISTENING line matching "TCP  127.0.0.1:8000  ...  LISTENING  <PID>"
                pattern = re.compile(
                    rf"^\s*TCP\s+{re.escape(host)}:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$",
                    re.IGNORECASE | re.MULTILINE,
                )
                for m in pattern.finditer(result.stdout):
                    pid_str = m.group(1)
                    if pid_str:
                        offenders.append((int(pid_str), "unknown", "netstat"))
        except Exception as e:
            _log(f"[CLEANUP] netstat fallback failed: {e!r}")
            _note_port_holder(f"[CLEANUP] netstat fallback failed: {e!r}")

    if not offenders:
        _log(f"[CLEANUP] No existing listener on {host}:{port}")
        _note_port_holder(f"[CLEANUP] No existing listener on {host}:{port}")
        return

    # Kill every offender we saw
    for (pid, name, source) in offenders:
        msg = f"[CLEANUP] Found listener on {host}:{port} -> PID {pid} ({name}) via {source}"
        _log(msg)
        _note_port_holder(msg)

        killed = False

        # Try graceful terminate/kill via psutil if it's there
        try:
            import psutil
            try:
                p = psutil.Process(pid)
                p.terminate()
                try:
                    p.wait(timeout=3)
                    killed = True
                except Exception:
                    pass

                if p.is_running():
                    _log(f"[CLEANUP] PID {pid} still alive after terminate(); forcing kill().")
                    p.kill()
                    try:
                        p.wait(timeout=3)
                        killed = True
                    except Exception:
                        pass
            except Exception as e:
                _log(f"[CLEANUP] psutil terminate/kill failed for PID {pid}: {e!r}")
        except Exception:
            # psutil import might fail, that's okay
            pass

        # If it's *still* running, hard kill with taskkill /F
        if not killed:
            try:
                import subprocess
                tk = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                _log(
                    f"[CLEANUP] taskkill /PID {pid} /F -> rc={tk.returncode} "
                    f"out={tk.stdout!r} err={tk.stderr!r}"
                )
                if tk.returncode == 0:
                    killed = True
            except Exception as e:
                _log(f"[CLEANUP] taskkill failed for PID {pid}: {e!r}")

        if killed:
            _log(f"[CLEANUP] PID {pid} terminated successfully.")
            _note_port_holder(f"[CLEANUP] PID {pid} terminated.")
        else:
            _log(f"[CLEANUP] WARNING: PID {pid} may still be holding {host}:{port}.")
            _note_port_holder(
                f"[CLEANUP] WARNING: PID {pid} may still be holding {host}:{port}."
            )

    _log(f"[CLEANUP] Port {host}:{port} cleanup pass complete.")
    _note_port_holder(f"[CLEANUP] Port {host}:{port} cleanup complete.")

def main() -> None:
    _log("=== backend_autostart begin ===")
    _log(f"python exe: {VENV_PY}")
    _log(f"cwd: {ROOT}")

    # clear stale pid/exit markers so the UI doesn't show old data
    if PID_FILE.exists():
        PID_FILE.unlink()
    if EXIT_FILE.exists():
        EXIT_FILE.unlink()

    # make sure nothing is already holding 127.0.0.1:8000
    _ensure_port_free(HOST, PORT)

    # open the new session markers in stdout/stderr logs
    sep = f"\n----- NEW LAUNCH {_ts()} -----\n"
    out_fh = BACKEND_OUT_LOG.open("a", buffering=1, encoding="utf-8")
    err_fh = BACKEND_ERR_LOG.open("a", buffering=1, encoding="utf-8")
    out_fh.write(sep)
    err_fh.write(sep)
    out_fh.flush()
    err_fh.flush()

    cmd = [
        str(VENV_PY),
        "-m",
        "uvicorn",
        API_MODULE,
        "--host", HOST,
        "--port", str(PORT),
        "--log-level", "info",
    ]

    _log(f"Attempting to launch uvicorn for {API_MODULE} on {HOST}:{PORT} ... cmd={cmd}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=os.environ.copy(),
            stdout=out_fh,
            stderr=err_fh,
            stdin=subprocess.DEVNULL,
            # On Windows, prevent console popups:
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception as e:  # noqa: BLE001 - best effort logging
        _log(f"FATAL: could not spawn uvicorn: {e!r}")
        err_fh.write(f"FATAL: could not spawn uvicorn: {e!r}\n")
        err_fh.flush()
        return

    # record PID so UI can show it even if it dies quickly
    _log(f"Spawned uvicorn PID={proc.pid}")
    with PID_FILE.open("w", encoding="utf-8") as f:
        f.write(str(proc.pid))

    # give uvicorn a short grace period to bind the port
    time.sleep(1.5)

    retcode = proc.poll()
    if retcode is None:
        # still running -> good
        _log(f"PID {proc.pid} appears alive after grace period.")
        return
    else:
        # crashed instantly; capture exit code
        with EXIT_FILE.open("w", encoding="utf-8") as f:
            f.write(str(retcode))
        _log(f"PID {proc.pid} exited early with code {retcode}")
        err_fh.flush()
        out_fh.flush()

if __name__ == "__main__":
    main()
