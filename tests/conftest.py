import os
from pathlib import Path

import pytest

from tests.fixtures.env_mode import require_mock, require_paper  # noqa: F401
from tests.fixtures.server_stack import server_stack  # noqa: F401

try:  # pragma: no cover - optional dependency guard
    import pytest_playwright  # type: ignore
except ImportError:  # pragma: no cover - executed when plugin unavailable
    pytest_playwright = None


@pytest.fixture(scope="session", autouse=True)
def env_mock_mode():
    os.environ.setdefault("MOCK_MODE", "true")
    os.environ.setdefault("GT_TEST_DISARM_KILL_SWITCH", "1")
    os.environ.setdefault("KILL_SWITCH", "0")
    os.environ.setdefault("KILL_SWITCH_FILE", str(Path(".pytest-no-kill.flag").resolve()))
    return os.environ["MOCK_MODE"]


if pytest_playwright is None:
    @pytest.fixture
    def page():  # pragma: no cover - exercised when playwright absent
        pytest.skip("playwright not installed")
