from __future__ import annotations
import os, pathlib, contextlib, inspect, pytest

# --- Register asyncio plugin even when PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ---
# Try both plugin module paths (older/newer versions)
pytest_plugins = [
    "tests.fixtures.server_stack",
    "tests.fixtures.env_mode",
]
try:
    import pytest_asyncio.plugin  # noqa: F401
    pytest_plugins.append("pytest_asyncio.plugin")
except Exception:
    pytest_plugins.append("pytest_asyncio")  # fallback

def pytest_sessionstart(session):
    # Default OFF unless a test explicitly sets ON
    os.environ.setdefault("GT_TEST_DISARM_KILL_SWITCH", "1")
    os.environ.setdefault("KILL_SWITCH", "0")
    os.environ.setdefault(
        "KILL_SWITCH_FILE",
        str(pathlib.Path(".pytest-no-kill.flag").resolve())
    )
    # Remove any repo-level kill-switch file so it can't hijack tests
    for rel in (
        "runtime/kill_switch", "runtime/kill_switch.flag",
        "runtime\\kill_switch", "runtime\\kill_switch.flag"
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

def pytest_collection_modifyitems(session, config, items):
    """
    Safety net: if any async test slipped through without @pytest.mark.asyncio,
    auto-mark it so pytest-asyncio runs it on an event loop.
    """
    for item in items:
        try:
            fn = item.obj  # bound function
        except Exception:
            continue
        if inspect.iscoroutinefunction(fn):
            # Add the mark only if not already present
            if not any(m.name == "asyncio" for m in item.own_markers):
                item.add_marker(pytest.mark.asyncio)
