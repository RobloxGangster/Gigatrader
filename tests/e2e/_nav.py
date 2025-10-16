import re
from playwright.sync_api import Page


def open_nav_and_select(page: Page, option_regex: str | re.Pattern):
    sidebar = page.locator('[data-testid="stSidebar"]')
    sidebar.wait_for(state="visible", timeout=30_000)

    combo = sidebar.get_by_role("combobox")
    combo.wait_for(state="visible", timeout=10_000)
    combo.click()

    page.get_by_role("option", name=re.compile(option_regex, re.I)).click()
