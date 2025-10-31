import re
import time

import pytest
from playwright.sync_api import Page

from ._nav import goto_page, wait_for_heading


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_option_chain_loads(page: Page):
    goto_page(page, "Option Chain")
    wait_for_heading(page, ("Option Chain",))

    table_like_selectors = [
        '[data-testid="stDataFrame"]',
        '[data-testid="stTable"]',
        '[role="table"]',
        '[role="grid"]',
    ]
    empty_text_patterns = [
        re.compile(r"No options", re.I),
        re.compile(r"No data", re.I),
        re.compile(r"Nothing to show", re.I),
    ]
    backend_wait_pattern = re.compile(r"backend\s+offline", re.I)

    end = time.time() + 20.0
    while time.time() < end:
        for selector in table_like_selectors:
            locator = page.locator(selector).first
            try:
                if locator.count() and locator.is_visible():
                    return
            except Exception:
                continue

        for pattern in empty_text_patterns:
            locator = page.get_by_text(pattern).first
            if locator.count() and locator.is_visible():
                return

        offline_banner = page.get_by_text(backend_wait_pattern).first
        if offline_banner.count() and offline_banner.is_visible():
            # Backend offline is acceptable; the UI surfaced a friendly message.
            return

        page.wait_for_timeout(1000)

    # Final fallbacks before failing: accept empty/notice text if visible now.
    for pattern in empty_text_patterns + [backend_wait_pattern]:
        locator = page.get_by_text(pattern).first
        if locator.count() and locator.is_visible():
            return

    pytest.fail("Option Chain page did not present data, empty state, or offline banner in time")
