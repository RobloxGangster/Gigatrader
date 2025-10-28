"""Utility to terminate the running backend process tracked in logs/backend.pid."""

from __future__ import annotations

import os
import signal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
PID_FILE = LOG_DIR / "backend.pid"
EXIT_FILE = LOG_DIR / "backend.exitcode"


def _write_exit(value: str | int | None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with EXIT_FILE.open("w", encoding="utf-8") as fh:
        fh.write("" if value is None else str(value))


def main() -> None:
    if not PID_FILE.exists():
        _write_exit("no_pid_file")
        return

    raw = PID_FILE.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        _write_exit("empty_pid")
        try:
            PID_FILE.unlink()
        except Exception:  # noqa: BLE001
            pass
        return

    try:
        pid = int(raw)
    except Exception:  # noqa: BLE001
        _write_exit(f"bad_pid:{raw}")
        try:
            PID_FILE.unlink()
        except Exception:  # noqa: BLE001
            pass
        return

    exit_val: str | int | None = None

    try:
        import psutil

        proc = psutil.Process(pid)
        proc.terminate()
        try:
            exit_val = proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
            try:
                exit_val = proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                exit_val = "killed"
    except ImportError:
        # Fallback if psutil is unavailable
        try:
            if os.name == "nt":
                os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
            exit_val = "terminated"
        except ProcessLookupError:
            exit_val = "not_found"
        except Exception as exc:  # noqa: BLE001
            exit_val = f"terminate_failed:{exc!r}"
    except psutil.NoSuchProcess:  # type: ignore[name-defined]
        exit_val = "not_found"
    except Exception as exc:  # noqa: BLE001
        exit_val = f"terminate_failed:{exc!r}"

    _write_exit(exit_val)

    try:
        PID_FILE.unlink()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
