import pytest
from playwright.sync_api import Page

from ._nav import (
    BASE_URL,
    LABEL_HEADINGS,
    click_run_diagnostics_if_present,
    goto_page,
    open_nav_and_select,
    wait_for_diagnostics_ready,
    wait_for_heading,
)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page: Page):
    goto_page(page, "Control Center")
    wait_for_heading(page, ("Control Center",))


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page: Page):
    # Try popover navigation first to cover selectbox/popover variants.
    navigated = False
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        open_nav_and_select(page, "Diagnostics / Logs")
        wait_for_heading(page, LABEL_HEADINGS["Diagnostics / Logs"])
        navigated = True
    except Exception:
        navigated = False

    if not navigated:
        # Fall back to robust helper which deep-links and retries the sidebar selectbox.
        goto_page(page, "Diagnostics / Logs")
        wait_for_heading(page, LABEL_HEADINGS["Diagnostics / Logs"])

    # If the button exists, click it; otherwise the page may auto-show logs
    clicked = click_run_diagnostics_if_present(page)

    # Whether clicked or not, wait for any acceptable “ready” signal
    wait_for_diagnostics_ready(page, timeout_ms=25000)
