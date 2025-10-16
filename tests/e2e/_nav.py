from __future__ import annotations
from playwright.sync_api import Page, TimeoutError as PWTimeout

NAV_LABEL = "Navigation"


def _click_nav_combobox(page: Page) -> None:
    nav_root = page.locator('[data-testid="nav-root"]').first
    try:
        nav_root.wait_for(state="attached", timeout=10_000)
        nav_root.wait_for(state="visible", timeout=10_000)
    except PWTimeout:
        pass

    sidebar_combo = page.locator('[data-testid="stSidebar"]').get_by_role("combobox").first
    try:
        sidebar_combo.wait_for(state="visible", timeout=5_000)
        sidebar_combo.click(timeout=5_000)
        return
    except PWTimeout:
        pass
    except Exception:
        pass

    try:
        page.get_by_label(NAV_LABEL, exact=True).first.click(timeout=5_000)
        return
    except Exception:
        pass

    # Final fallback: first visible combobox anywhere
    combo_any = page.get_by_role("combobox").first
    combo_any.wait_for(state="visible", timeout=10_000)
    combo_any.click()


def open_nav_and_select(page: Page, option_text: str) -> None:
    _click_nav_combobox(page)
    page.get_by_role("option", name=option_text, exact=True).click(timeout=10_000)
