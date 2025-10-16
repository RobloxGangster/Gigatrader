from __future__ import annotations

import contextlib
import os
import pathlib
import subprocess
import sys
import time

import pytest
import requests


def pytest_sessionstart(session):  # runs before test collection/imports
    os.environ.setdefault("GT_TEST_DISARM_KILL_SWITCH", "1")
    os.environ.setdefault("KILL_SWITCH", "0")
    os.environ.setdefault(
        "KILL_SWITCH_FILE", str(pathlib.Path(".pytest-no-kill.flag").resolve())
    )
    for rel in (
        "runtime/kill_switch",
        "runtime/kill_switch.flag",
        "runtime\\kill_switch",
        "runtime\\kill_switch.flag",
    ):
        p = pathlib.Path(rel)
        if p.exists():
            with contextlib.suppress(Exception):
                p.unlink()


@pytest.fixture(autouse=True)
def _default_disarm_kill_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("GT_TEST_DISARM_KILL_SWITCH", "1")
    monkeypatch.setenv("KILL_SWITCH", "0")
    monkeypatch.setenv("KILL_SWITCH_FILE", str(tmp_path / "no_kill.flag"))


def pytest_addoption(parser) -> None:
    """Provide fallbacks for Playwright CLI flags when the plugin is absent."""
    for opt in ("--screenshot", "--video", "--tracing"):
        try:
            parser.addoption(opt, action="store", default=None, help="(noop fallback)")
        except ValueError:
            # Option already provided by an installed plugin; ignore.
            pass


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
LOGS = ROOT / "logs"
RUNTIME.mkdir(exist_ok=True, parents=True)
LOGS.mkdir(exist_ok=True, parents=True)

API_PORT = int(os.getenv("GT_API_PORT", "8000"))
UI_PORT = int(os.getenv("GT_UI_PORT", "8501"))


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
    return os.getenv("MOCK_MODE", "").lower() in ("1", "true", "yes", "on")


@pytest.fixture(scope="session", autouse=True)
def ensure_browsers():
    # Install Chromium once if needed (no-op if installed)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)


@contextlib.contextmanager
def _spawn(cmd, cwd=None, env=None, stdout_path=None, stderr_path=None):
    """Start a child process without sending CTRL_BREAK during teardown."""
    out = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    err = open(stderr_path, "wb") if stderr_path else subprocess.DEVNULL
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=err, creationflags=flags)
    try:
        yield p
    finally:
        with contextlib.suppress(Exception):
            p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            with contextlib.suppress(Exception):
                p.kill()
        for fh in (out, err):
            if fh not in (None, subprocess.DEVNULL):
                with contextlib.suppress(Exception):
                    fh.close()


@pytest.fixture(scope="session")
def server_stack(env_mock_mode):
    """Start backend (uvicorn) and Streamlit UI; tear down after session."""
    env = os.environ.copy()
    # Default to MOCK true unless user set it (safety)
    if "MOCK_MODE" not in env:
        env["MOCK_MODE"] = "true"
    env.setdefault("PYTHONPATH", str(ROOT))

    backend_out = RUNTIME / "test_backend.out.log"
    backend_err = RUNTIME / "test_backend.err.log"
    ui_out = RUNTIME / "test_streamlit.out.log"
    ui_err = RUNTIME / "test_streamlit.err.log"

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(API_PORT),
    ]
    ui_cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "ui/Home.py",
        "--server.port",
        str(UI_PORT),
        "--server.headless",
        "true",
    ]

    with _spawn(backend_cmd, cwd=str(ROOT), env=env, stdout_path=backend_out, stderr_path=backend_err):
        assert _wait_http(f"http://127.0.0.1:{API_PORT}/health", timeout=60), "backend did not become healthy"
        with _spawn(ui_cmd, cwd=str(ROOT), env=env, stdout_path=ui_out, stderr_path=ui_err):
            assert _wait_http(f"http://127.0.0.1:{UI_PORT}/", timeout=60), "ui did not become healthy"
            yield dict(api=f"http://127.0.0.1:{API_PORT}", ui=f"http://127.0.0.1:{UI_PORT}")


def _skip_if(cond, reason):
    if cond:
        pytest.skip(reason)


@pytest.fixture
def require_mock(env_mock_mode):
    _skip_if(not env_mock_mode, "mock_only test; set MOCK_MODE=true")


@pytest.fixture
def require_paper(env_mock_mode):
    _skip_if(env_mock_mode, "paper_only test; set MOCK_MODE=false")


def pytest_configure(config):
    # Register the mark in case plugin loading order changes
    config.addinivalue_line("markers", "asyncio: mark test to run with asyncio event loop")
