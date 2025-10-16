from playwright.sync_api import Page


def open_nav_and_select(page: Page, label: str) -> None:
    # Click the single sidebar combobox labeled "Navigation"
    page.get_by_label("Navigation", exact=True).click(timeout=10_000)
    page.get_by_role("option", name=label, exact=True).click(timeout=10_000)
