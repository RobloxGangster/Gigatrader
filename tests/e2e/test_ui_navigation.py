import pytest
from playwright.sync_api import Page

from ._nav import (
    goto_page,
    wait_for_heading,
    LABEL_HEADINGS,
    click_run_diagnostics_if_present,
    wait_for_diagnostics_ready,
)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page: Page):
    goto_page(page, "Control Center")
    wait_for_heading(page, ("Control Center",))


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page: Page):
    # Navigate via deep-link (with UI fallback inside goto_page)
    goto_page(page, "Diagnostics / Logs")

    # Accept multiple headings (copy varies across builds)
    wait_for_heading(page, LABEL_HEADINGS["Diagnostics / Logs"])

    # If the button exists, click it; otherwise the page may auto-show logs
    clicked = click_run_diagnostics_if_present(page)

    # Whether clicked or not, wait for any acceptable “ready” signal
    wait_for_diagnostics_ready(page, timeout_ms=25000)
