from __future__ import annotations

import os

import pytest
from playwright.sync_api import sync_playwright


os.environ.setdefault("PWTEST_SCREENSHOT", "off")
os.environ.setdefault("PWTEST_VIDEO", "off")
os.environ.setdefault("PWTEST_TRACING", "off")


@pytest.fixture(scope="session")
def _pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(_pw):
    browser = _pw.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture(scope="function")
def page(browser):
    ctx = browser.new_context(no_viewport=True)
    pg = ctx.new_page()
    try:
        yield pg
    finally:
        ctx.close()
