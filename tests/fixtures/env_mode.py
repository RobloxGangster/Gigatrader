from __future__ import annotations
import os
import pytest


def _truthy(s: str | None) -> bool:
    return (s or "").strip().lower() in {"1", "true", "on", "yes"}


@pytest.fixture
def require_mock():
    """Skip if not running with MOCK_MODE=true."""
    if not _truthy(os.getenv("MOCK_MODE", "true")):
        pytest.skip("mock_only test; set MOCK_MODE=true")


@pytest.fixture
def require_paper():
    """Skip if not running with MOCK_MODE=false."""
    if _truthy(os.getenv("MOCK_MODE", "true")):
        pytest.skip("paper_only test; set MOCK_MODE=false")
