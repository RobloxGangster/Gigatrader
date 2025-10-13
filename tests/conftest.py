import os
import pathlib
import pytest


@pytest.fixture(scope="session", autouse=True)
def _disable_killswitch_for_tests():
    """Ensure kill-switch does not interfere with test execution."""

    os.environ["DISABLE_KILL_SWITCH_FOR_TESTS"] = "1"
    ks = pathlib.Path(".kill_switch")
    try:
        if ks.exists():
            ks.unlink()
    except Exception:
        pass
    yield
