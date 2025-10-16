import re
from playwright.sync_api import Page, TimeoutError as PWTimeoutError


def _click_nav_combobox(page: Page):
    # Scope to the sidebar, then to the combobox whose accessible name contains 'Navigation'
    sidebar = page.locator('[data-testid="stSidebar"]')
    sidebar.wait_for(state="visible", timeout=30_000)

    # Prefer label match; fallback to the first combobox that exposes a "Control Center" option
    try:
        combo = sidebar.get_by_label(re.compile(r"\bNavigation\b", re.I))
        combo.wait_for(state="visible", timeout=10_000)
        combo.click()
        return
    except PWTimeoutError:
        pass

    # Fallback: pick the first combobox and open it
    combo_any = sidebar.get_by_role("combobox").first
    combo_any.wait_for(state="visible", timeout=10_000)
    combo_any.click()


def open_nav_and_select_exact(page: Page, *names_in_priority_order: str):
    """
    Open the sidebar nav selectbox and click the first matching option by **exact** text.
    Falls back among provided names (e.g., 'Diagnostics / Logs', then 'Logs').
    """
    _click_nav_combobox(page)

    last_err = None
    for name in names_in_priority_order:
        try:
            # Use exact accessible name; avoids JS regex issues with '/'
            page.get_by_role("option", name=name, exact=True).click()
            return
        except Exception as e:
            last_err = e
            # If the dropdown auto-closed, open it again and try next candidate
            _click_nav_combobox(page)
            continue
    # Final fallback: try a regex that **escapes forward slashes**
    try:
        pat = re.compile(r"|".join([re.escape(n) for n in names_in_priority_order]), re.I)
        page.get_by_role("option", name=pat).click()
        return
    except Exception as e:
        raise last_err or e
