from __future__ import annotations
import os, pytest
from playwright.sync_api import Page, expect
from ._nav import open_nav_and_select

UI = os.getenv("GT_UI_URL", "http://127.0.0.1:8501")


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_option_chain_loads(page: Page):
    page.goto(UI, timeout=60_000, wait_until="domcontentloaded")
    open_nav_and_select(page, "Option Chain")

    # Be lenient: accept either heading or core form elements as evidence of load
    try:
        expect(page.get_by_role("heading", name="Option Chain & Greeks")).to_be_visible(timeout=10_000)
    except Exception:
        # fallback: look for common controls the page renders (symbol input)
        expect(page.get_by_label("Underlying")).to_be_visible(timeout=10_000)
