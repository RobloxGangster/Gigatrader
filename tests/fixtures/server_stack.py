from __future__ import annotations
import os, sys, time, contextlib, subprocess, requests, pytest

API_PORT = int(os.getenv("GT_API_PORT", "8000"))
HEALTH_URL = f"http://127.0.0.1:{API_PORT}/health"

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


@pytest.fixture(scope="session")
def server_stack():
    """Start FastAPI backend for integration/E2E and tear it down safely."""
    p = _spawn_backend()
    try:
        _wait_ready()
        yield
    finally:
        with contextlib.suppress(Exception):
            p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            with contextlib.suppress(Exception):
                p.kill()
