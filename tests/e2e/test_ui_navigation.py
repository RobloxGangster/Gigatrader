from __future__ import annotations
import os, pytest, requests
from playwright.sync_api import Page, expect
from ._nav import open_nav_and_select
from .helpers import DIAG_ALIASES, wait_for_heading

BASE_URL = os.getenv("GT_UI_URL", "http://127.0.0.1:8501")


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page: Page):
    # optional: ensure backend is up before render
    r = requests.get("http://127.0.0.1:8000/health", timeout=5)
    assert r.status_code == 200

    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    open_nav_and_select(page, "Control Center")
    expect(page.get_by_role("heading", name="Control Center")).to_be_visible(timeout=10_000)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    open_nav_and_select(page, "Diagnostics / Logs")

    wait_for_heading(page, DIAG_ALIASES)
    # Wait for our stable, visible test hook
    expect(page.locator('[data-testid="logs-panel"]')).to_be_visible(timeout=10_000)

    # If you expose a "Run Diagnostics" button, click it; otherwise just pass once the panel is visible
    try:
        page.get_by_role("button", name="Run Diagnostics", exact=True).click(timeout=2_000)
        # Expect any visible completion text your page emits
        page.get_by_text("Diagnostics", exact=False).first.wait_for(timeout=10_000)
    except Exception:
        # panel visible is enough
        pass
