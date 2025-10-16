from playwright.sync_api import Page, expect
import re
import urllib.parse
import time

BASE = "http://127.0.0.1:8501"


def _slug(label: str) -> str:
    return (
        label.lower()
        .replace("&", "and")
        .replace("/", "")
        .replace(" ", "-")
    )


def wait_app_ready(page: Page, timeout=15000):
    page.locator('[data-testid="app-ready"]').first.wait_for(timeout=timeout)


def _wait_heading_or_text(page: Page, label: str, timeout_ms: int = 6000) -> bool:
    # Prefer heading role, then text fallback
    deadline = time.time() + (timeout_ms / 1000.0)
    patt = re.compile(rf"^{re.escape(label)}$", re.I)
    while time.time() < deadline:
        try:
            expect(page.get_by_role("heading", name=patt).first).to_be_visible(timeout=800)
            return True
        except Exception:
            pass
        try:
            page.get_by_text(patt).first.wait_for(timeout=800)
            return True
        except Exception:
            pass
    return False


def goto_page(page: Page, label: str, timeout=30000):
    """Prefer deep link; fallback to selectbox only if the requested page is not visible."""
    slug = _slug(label)
    url = f"{BASE}?page={urllib.parse.quote(slug)}"
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try:
        wait_app_ready(page, timeout=15000)
    except Exception:
        # Even if app-ready sentinel isn't found quickly, still check heading before falling back
        pass

    # If the correct page content is already there, don't touch the dropdown.
    if _wait_heading_or_text(page, label, timeout_ms=3000):
        return

    # Fallback to dropdown selection when heading isn't present.
    open_nav_and_select(page, rf"^{re.escape(label)}$")


def _open_selectbox_popover(page: Page):
    """
    Click the 'Navigation' selectbox and ensure its popover/listbox is visible.
    Streamlit can render it without 'role=option', so we check for a generic menu/listbox container.
    """
    # Prefer a named combobox so we’re robust to layout changes
    try:
        combo = page.get_by_role("combobox", name=re.compile(r"^Navigation$", re.I)).first
        combo.wait_for(state="visible", timeout=10000)
        combo.click()
    except Exception:
        # Fallback to first visible combobox anywhere
        combo = page.get_by_role("combobox").first
        combo.wait_for(state="visible", timeout=15000)
        combo.click()

    # Ensure the popover actually opened before we look for an option
    # Try common containers Streamlit uses for options
    menu = page.locator('[role="listbox"], [data-baseweb="menu"], div[aria-expanded="true"]').first
    try:
        menu.wait_for(state="visible", timeout=5000)
    except Exception:
        # As a last resort, press ArrowDown to force it to open
        page.keyboard.press("ArrowDown")
        menu.wait_for(state="visible", timeout=5000)

    return menu


def open_nav_and_select(page: Page, regex_pattern: str):
    """
    Select by visible text match inside the popover (not strictly by role=option).
    """
    menu = _open_selectbox_popover(page)

    # Try role=option first if present…
    try:
        opt = page.get_by_role("option", name=re.compile(regex_pattern, re.I)).first
        opt.wait_for(timeout=2000)
        opt.click()
        return
    except Exception:
        pass

    # …then fall back to text search in the open menu container
    opt_text = menu.get_by_text(re.compile(regex_pattern, re.I)).first
    opt_text.wait_for(timeout=4000)
    opt_text.click()


def wait_for_heading(page: Page, names):
    if isinstance(names, str):
        names = [names]
    for name in names:
        if _wait_heading_or_text(page, name, timeout_ms=6000):
            return
    raise AssertionError(f"None of the headings matched: {names}")
