from __future__ import annotations
import os, sys, time, contextlib, subprocess, requests, pytest

API_PORT = int(os.getenv("GT_API_PORT", "8000"))
UI_PORT = int(os.getenv("GT_UI_PORT", os.getenv("STREAMLIT_SERVER_PORT", "8501")))
HEALTH_URL = f"http://127.0.0.1:{API_PORT}/health"
UI_URL = f"http://127.0.0.1:{UI_PORT}"

def _spawn_backend():
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.getcwd())
    env.setdefault("MOCK_MODE", "true")
    # Put backend in its own process group so teardown signals don't nuke pytest on Windows
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    p = subprocess.Popen(
        [sys.executable, "-m", "backend.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    return p


def _spawn_ui():
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.getcwd())
    env.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    env.setdefault("STREAMLIT_SERVER_PORT", str(UI_PORT))
    env.setdefault("STREAMLIT_BROWSER_GATHERUSAGESTATS", "false")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "ui/app.py",
        "--server.port",
        str(UI_PORT),
        "--server.headless",
        "true",
    ]
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )


def _wait_ready(timeout=20.0):
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            r = requests.get(HEALTH_URL, timeout=2.0)
            if r.status_code == 200:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.25)
    raise RuntimeError(f"Backend not ready at {HEALTH_URL}: {last_exc!r}")


def _wait_ui_ready(timeout=30.0):
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            r = requests.get(UI_URL, timeout=2.0)
            if r.status_code == 200:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.25)
    raise RuntimeError(f"UI not ready at {UI_URL}: {last_exc!r}")


@pytest.fixture(scope="session")
def server_stack():
    """Start FastAPI backend for integration/E2E and tear it down safely."""
    backend = _spawn_backend()
    ui_proc = _spawn_ui()
    try:
        _wait_ready()
        _wait_ui_ready()
        yield
    finally:
        with contextlib.suppress(Exception):
            backend.terminate()
        with contextlib.suppress(Exception):
            ui_proc.terminate()
        for proc in (backend, ui_proc):
            try:
                proc.wait(timeout=8)
            except Exception:
                with contextlib.suppress(Exception):
                    proc.kill()
