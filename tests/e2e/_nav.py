from playwright.sync_api import Page, expect
import re
import urllib.parse

BASE = "http://127.0.0.1:8501"


def wait_app_ready(page: Page, timeout=15000):
    page.locator('[data-testid="app-ready"]').first.wait_for(timeout=timeout)


def goto_page(page: Page, label: str, timeout=30000):
    """First try query-param deep link; fallback to combobox if needed."""
    slug = label.lower().replace(" ", "-").replace("/", "").replace("&", "and")
    url = f"{BASE}?page={urllib.parse.quote(slug)}"
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try:
        wait_app_ready(page, timeout=15000)
        return
    except Exception:
        open_nav_and_select(page, f"^{re.escape(label)}$")


def open_nav_and_select(page: Page, pattern: str):
    """Open any visible combobox and select the option by regex pattern."""
    try:
        combo_named = page.get_by_role("combobox", name=re.compile(r"^Navigation$", re.I)).first
        combo_named.wait_for(state="visible", timeout=10000)
        combo_named.click()
    except Exception:
        any_combo = page.get_by_role("combobox").first
        any_combo.wait_for(state="visible", timeout=15000)
        any_combo.click()

    opt = page.get_by_role("option", name=re.compile(pattern, re.I)).first
    opt.wait_for(timeout=10000)
    opt.click()


def wait_for_heading(page: Page, names):
    if isinstance(names, str):
        names = [names]
    for name in names:
        try:
            expect(page.get_by_role("heading", name=re.compile(name, re.I)).first).to_be_visible(timeout=8000)
            return
        except Exception:
            pass
    for name in names:
        try:
            page.get_by_text(re.compile(name, re.I)).first.wait_for(timeout=5000)
            return
        except Exception:
            pass
    raise AssertionError(f"None of the headings matched: {names}")
