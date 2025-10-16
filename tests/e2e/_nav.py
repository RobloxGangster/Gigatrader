import re
from playwright.sync_api import Page


def open_nav_and_select(page: Page, option_regex: str | re.Pattern):
    # Scope to sidebar
    sidebar = page.locator('[data-testid="stSidebar"]')
    sidebar.wait_for(state="visible", timeout=30_000)

    # Streamlit renders multiple comboboxes; pick the one labeled "Navigation"
    combo = sidebar.get_by_label(re.compile(r"\bNavigation\b", re.I))
    combo.wait_for(state="visible", timeout=10_000)
    combo.click()

    # Choose the target page by name (regex allowed)
    page.get_by_role("option", name=re.compile(option_regex, re.I)).click()
