# tests/e2e/conftest.py
# Force-load the Playwright plugin so 'page' is available even with autoload disabled.
pytest_plugins = ("pytest_playwright",)

# Optional: if you use pytest-base-url, this keeps its plugin available too.
try:
    import pytest_base_url  # noqa: F401
    pytest_plugins += ("pytest_base_url.plugin",)
except Exception:
    pass
