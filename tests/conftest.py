from __future__ import annotations
import os, time, subprocess, sys, signal, pathlib, contextlib
import pytest, requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
LOGS = ROOT / "logs"
RUNTIME.mkdir(exist_ok=True, parents=True)
LOGS.mkdir(exist_ok=True, parents=True)

API_PORT = int(os.getenv("GT_API_PORT", "8000"))
UI_PORT  = int(os.getenv("GT_UI_PORT",  "8501"))

def _wait_http(url: str, timeout=40) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False

@pytest.fixture(scope="session")
def env_mock_mode():
    return os.getenv("MOCK_MODE", "").lower() in ("1","true","yes","on")

@pytest.fixture(scope="session", autouse=True)
def ensure_browsers():
    # Install Chromium once if needed (no-op if installed)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)

@contextlib.contextmanager
def _spawn(cmd, cwd=None, env=None, stdout_path=None, stderr_path=None):
    out = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    err = open(stderr_path, "wb") if stderr_path else subprocess.DEVNULL
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=err)
    try:
        yield p
    finally:
        with contextlib.suppress(Exception):
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)
            p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                p.kill()
        if out not in (None, subprocess.DEVNULL): out.close()
        if err not in (None, subprocess.DEVNULL): err.close()

@pytest.fixture(scope="session")
def server_stack(env_mock_mode):
    """Start backend (uvicorn) and Streamlit UI; tear down after session."""
    env = os.environ.copy()
    # Default to MOCK true unless user set it (safety)
    if "MOCK_MODE" not in env: env["MOCK_MODE"] = "true"
    env.setdefault("PYTHONPATH", str(ROOT))

    backend_out = RUNTIME / "test_backend.out.log"
    backend_err = RUNTIME / "test_backend.err.log"
    ui_out = RUNTIME / "test_streamlit.out.log"
    ui_err = RUNTIME / "test_streamlit.err.log"

    backend_cmd = [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(API_PORT)]
    ui_cmd = [sys.executable, "-m", "streamlit", "run", "ui/Home.py", "--server.port", str(UI_PORT), "--server.headless", "true"]

    with _spawn(backend_cmd, cwd=str(ROOT), env=env, stdout_path=backend_out, stderr_path=backend_err):
        assert _wait_http(f"http://127.0.0.1:{API_PORT}/health", timeout=60), "backend did not become healthy"
        with _spawn(ui_cmd, cwd=str(ROOT), env=env, stdout_path=ui_out, stderr_path=ui_err):
            assert _wait_http(f"http://127.0.0.1:{UI_PORT}/", timeout=60), "ui did not become healthy"
            yield dict(api=f"http://127.0.0.1:{API_PORT}", ui=f"http://127.0.0.1:{UI_PORT}")

def _skip_if(cond, reason):
    if cond: pytest.skip(reason)

@pytest.fixture
def require_mock(env_mock_mode):
    _skip_if(not env_mock_mode, "mock_only test; set MOCK_MODE=true")

@pytest.fixture
def require_paper(env_mock_mode):
    _skip_if(env_mock_mode, "paper_only test; set MOCK_MODE=false")
