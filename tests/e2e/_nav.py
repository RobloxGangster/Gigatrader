import re
from playwright.sync_api import Page, TimeoutError as PWTimeoutError


def _click_nav_combobox(page: Page):
    sidebar = page.locator('[data-testid="stSidebar"]')
    sidebar.wait_for(state="visible", timeout=30_000)
    try:
        combo = sidebar.get_by_label(re.compile(r"\bNavigation\b", re.I))
        combo.wait_for(state="visible", timeout=10_000)
        combo.click()
        return
    except PWTimeoutError:
        pass
    combo_any = sidebar.get_by_role("combobox").first
    combo_any.wait_for(state="visible", timeout=10_000)
    combo_any.click()


def open_nav_and_select_exact(page: Page, *names_in_priority_order: str):
    _click_nav_combobox(page)
    last_err = None
    for name in names_in_priority_order:
        try:
            page.get_by_role("option", name=name, exact=True).click()
            return
        except Exception as e:
            last_err = e
            _click_nav_combobox(page)
            continue
    pat = re.compile(r"|".join([re.escape(n) for n in names_in_priority_order]), re.I)
    page.get_by_role("option", name=pat).click()


# --- Back-compat alias used by some tests ---
def open_nav_and_select(page: Page, option_regex_or_exact: str):
    """
    If the caller passes an exact title, prefer exact match.
    If it's clearly a regex pattern, fall back to regex.
    """
    metas = set(".^$*+?{}[]|()")
    if any(ch in metas for ch in option_regex_or_exact):
        _click_nav_combobox(page)
        page.get_by_role("option", name=re.compile(option_regex_or_exact, re.I)).click()
        return
    open_nav_and_select_exact(page, option_regex_or_exact, "Logs")
