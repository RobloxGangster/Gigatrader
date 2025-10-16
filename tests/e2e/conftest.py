from __future__ import annotations
import pytest


def pytest_configure(config):
    # Force-load the plugin even when PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
    if config.pluginmanager.has_plugin("pytest_playwright"):
        return
    try:
        config.pluginmanager.import_plugin("pytest_playwright")
    except ValueError as e:
        if "pytest_asyncio.plugin" not in str(e):
            config._gt_pw_err = e  # type: ignore[attr-defined]
    except Exception as e:
        # Remember why it failed and skip e2e tests during collection
        config._gt_pw_err = e  # type: ignore[attr-defined]


def pytest_collection_modifyitems(config, items):
    err = getattr(config, "_gt_pw_err", None)
    if not err:
        return
    skip_mark = pytest.mark.skip(reason=f"pytest-playwright unavailable: {err}")
    for item in items:
        # Only skip tests in this e2e suite
        if "e2e" in item.keywords:
            item.add_marker(skip_mark)
