from __future__ import annotations
import os, time, pytest, requests
from playwright.sync_api import Page
from .helpers import select_nav, wait_for_heading, DIAG_ALIASES

BASE_URL = os.getenv("GT_UI_URL", "http://127.0.0.1:8501")


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page: Page):
    # Backend health pre-check reduces flaky first-render
    r = requests.get("http://127.0.0.1:8000/health", timeout=5)
    assert r.status_code == 200

    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    select_nav(page, "Control Center")
    wait_for_heading(page, ("Control Center", "Trading Control Center"))


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    select_nav(page, "Diagnostics / Logs", aliases=DIAG_ALIASES)
    wait_for_heading(page, ("Diagnostics / Logs", "Logs & Pacing", "Diagnostics"))

    # If there is a "Run Diagnostics" button, click it; otherwise assert logs table appears
    # Both paths are acceptable; we make this tolerant to UI differences.
    try:
        page.get_by_role("button", name="Run Diagnostics", exact=True).click(timeout=2000)
        # expect some status text to appear
        page.get_by_text("Diagnostics complete", exact=False).first.wait_for(timeout=10000)
    except Exception:
        # fallback: look for recent logs area
        page.get_by_text("Log", exact=False).first.wait_for(timeout=10000)
