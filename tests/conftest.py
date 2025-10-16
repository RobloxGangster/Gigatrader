from __future__ import annotations
import os, pathlib, contextlib, pytest

# Make sure asyncio support is always on even when plugin autoload is disabled
pytest_plugins = ("pytest_asyncio", "tests.fixtures.server_stack")

def pytest_sessionstart(session):
    # Disarm kill-switch by default so tests assert intended risk reasons
    os.environ.setdefault("GT_TEST_DISARM_KILL_SWITCH", "1")
    os.environ.setdefault("KILL_SWITCH", "0")
    os.environ.setdefault(
        "KILL_SWITCH_FILE",
        str(pathlib.Path(".pytest-no-kill.flag").resolve())
    )
    # Clean only repo-level permanent switch if it exists
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
