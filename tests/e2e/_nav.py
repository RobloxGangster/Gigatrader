from playwright.sync_api import Page


def _click_nav_combobox(page: Page) -> None:
    # Try sidebar first
    combo = page.locator('[data-testid="stSidebar"] >> role=combobox').first
    if combo.count() and combo.is_visible():
        combo.click()
        return
    # Fallback: any visible combobox (top bar / main)
    page.get_by_role("combobox").first.wait_for(state="visible", timeout=15_000)
    page.get_by_role("combobox").first.click()


def open_nav_and_select(page: Page, pattern: str) -> None:
    _click_nav_combobox(page)
    # Match by exact visible option text (case-insensitive)
    option = page.get_by_role("option", name=pattern, exact=False).first
    option.wait_for(timeout=10_000)
    option.click()
