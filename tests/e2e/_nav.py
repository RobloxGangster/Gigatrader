from __future__ import annotations
from playwright.sync_api import Page, TimeoutError as PWTimeout

NAV_LABEL = "Navigate"

def _click_nav_combobox(page: Page) -> None:
    # Prefer the labeled selectbox anywhere on the page
    try:
        page.get_by_label(NAV_LABEL, exact=True).click(timeout=5_000)
        return
    except Exception:
        pass

    # Fallback: named combobox
    try:
        page.get_by_role("combobox", name=NAV_LABEL, exact=True).click(timeout=5_000)
        return
    except Exception:
        pass

    # Final fallback: first visible combobox
    combo_any = page.get_by_role("combobox").first
    combo_any.wait_for(state="visible", timeout=10_000)
    combo_any.click()


def open_nav_and_select(page: Page, option_text: str) -> None:
    _click_nav_combobox(page)
    page.get_by_role("option", name=option_text, exact=True).click(timeout=10_000)
