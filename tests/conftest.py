from __future__ import annotations
import os, pathlib, contextlib, pytest

# Register plugins early even when PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
pytest_plugins = (
    "pytest_asyncio",               # async support
    "tests.fixtures.server_stack",  # backend launcher
    "tests.fixtures.env_mode",      # require_mock / require_paper
)


def pytest_sessionstart(session):
    # Disarm kill-switch by default; tests that need ON will set explicit env/file.
    os.environ.setdefault("GT_TEST_DISARM_KILL_SWITCH", "1")
    os.environ.setdefault("KILL_SWITCH", "0")
    os.environ.setdefault("KILL_SWITCH_FILE", str(pathlib.Path(".pytest-no-kill.flag").resolve()))
    # Remove any repo-level kill-switch file so it can't hijack tests
    for rel in ("runtime/kill_switch", "runtime/kill_switch.flag",
                "runtime\\kill_switch", "runtime\\kill_switch.flag"):
        p = pathlib.Path(rel)
        if p.exists():
            with contextlib.suppress(Exception):
                p.unlink()


@pytest.fixture(autouse=True)
def _default_disarm_kill_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("GT_TEST_DISARM_KILL_SWITCH", "1")
    monkeypatch.setenv("KILL_SWITCH", "0")
    monkeypatch.setenv("KILL_SWITCH_FILE", str(tmp_path / "no_kill.flag"))
