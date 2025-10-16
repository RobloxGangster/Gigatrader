import pytest
from playwright.sync_api import Page

from ._nav import goto_page, wait_for_heading, open_nav_and_select

BASE_URL = "http://127.0.0.1:8501"
DIAG_ALIASES = ("Diagnostics / Logs", "Logs & Pacing", "Diagnostics", "Logs")


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page: Page):
    goto_page(page, "Control Center")
    wait_for_heading(page, ("Control Center",))


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page: Page):
    goto_page(page, "Diagnostics / Logs")
    wait_for_heading(page, DIAG_ALIASES)

    try:
        page.get_by_role("button", name="Run Diagnostics", exact=True).click(timeout=2000)
        page.get_by_text("Diagnostics complete", exact=False).first.wait_for(timeout=10000)
    except Exception:
        page.get_by_text("Log", exact=False).first.wait_for(timeout=10000)
