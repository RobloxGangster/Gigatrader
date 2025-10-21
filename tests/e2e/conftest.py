"""E2E test fixtures and guards."""

from __future__ import annotations

import importlib.util

import pytest


if importlib.util.find_spec("playwright") is None:
    pytest.skip("playwright not installed", allow_module_level=True)
