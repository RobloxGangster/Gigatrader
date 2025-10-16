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


def _sentinel_for(label: str) -> str:
    # Map label -> data-testid set in each page
    label_low = label.lower()
    if "option chain" in label_low:
        return "page-option-chain"
    if "control center" in label_low:
        return "page-control-center"
    if "diagnostics" in label_low or "logs" in label_low:
        return "page-diagnostics"
    # fallback none
    return ""


def wait_app_ready(page: Page, timeout=15000):
    page.locator('[data-testid="app-ready"]').first.wait_for(timeout=timeout)


def _url_contains_slug(page: Page, slug: str) -> bool:
    return f"page={slug}" in page.url.lower()


def _wait_heading_or_sentinel(page: Page, label: str, timeout_ms: int = 12000) -> bool:
    """Return True as soon as either the title heading OR the page sentinel is visible."""
    deadline = time.time() + (timeout_ms / 1000.0)
    patt = re.compile(rf"^{re.escape(label)}$", re.I)
    sentinel = _sentinel_for(label)
    while time.time() < deadline:
        if sentinel:
            try:
                page.locator(f'[data-testid="{sentinel}"]').first.wait_for(timeout=600)
                return True
            except Exception:
                pass
        try:
            expect(page.get_by_role("heading", name=patt).first).to_be_visible(timeout=600)
            return True
        except Exception:
            pass
        time.sleep(0.05)
    return False


def goto_page(page: Page, label: str, timeout=30000):
    """
    Prefer deep-link (?page=slug) and wait for a page-specific sentinel/heading.
    Only fall back to the dropdown if slug isn't applied or content isn't rendered
    even after a single reload attempt.
    """
    slug = _slug(label)
    url = f"{BASE}?page={urllib.parse.quote(slug)}"
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)

    # Try to stabilize on the deep-link
    try:
        wait_app_ready(page, timeout=12000)
    except Exception:
        # app-ready sentinel might be hidden; carry on with content checks
        pass

    # If slug is present in URL, commit to waiting for content instead of dropdown
    if _url_contains_slug(page, slug):
        if _wait_heading_or_sentinel(page, label, timeout_ms=8000):
            return
        # attempt a single reload; sometimes Streamlit pages render after a refresh
        page.reload(wait_until="domcontentloaded")
        if _wait_heading_or_sentinel(page, label, timeout_ms=8000):
            return
        # Only now consider dropdown fallback
        open_nav_and_select(page, rf"^{re.escape(label)}$")
        _wait_heading_or_sentinel(page, label, timeout_ms=8000)
        return

    # If slug wasn't applied (rare), try dropdown immediately
    open_nav_and_select(page, rf"^{re.escape(label)}$")
    _wait_heading_or_sentinel(page, label, timeout_ms=8000)


def _open_selectbox_popover(page: Page):
    """
    Open the 'Navigation' selectbox popover. This is a last resort path now.
    We don't assert strongly on menu container; we just ensure the click likely took effect.
    """
    # Prefer the labeled combobox
    try:
        combo = page.get_by_role("combobox", name=re.compile(r"^Navigation$", re.I)).first
        combo.scroll_into_view_if_needed()
        combo.wait_for(state="visible", timeout=10000)
        combo.click()
    except Exception:
        combo = page.get_by_role("combobox").first
        combo.scroll_into_view_if_needed()
        combo.wait_for(state="visible", timeout=15000)
        combo.click()

    # Try common menu/listbox containers, but don't hard-fail if we cannot assert visibility quickly
    containers = [
        '[role="listbox"]',
        '[data-baseweb="menu"]',
        'div[aria-expanded="true"]',
        'div[role="dialog"]',
        'div[role="menu"]',
    ]
    menu = None
    for sel in containers:
        cand = page.locator(sel).first
        try:
            cand.wait_for(state="visible", timeout=1200)
            menu = cand
            break
        except Exception:
            continue

    # If no explicit container found, rely on text click later
    return menu or page.locator("body")


def open_nav_and_select(page: Page, regex_pattern: str):
    """
    Select by visible text match; try role=option first, then pure text anywhere
    (popover or body) to accommodate frameworks that don't expose listbox roles.
    """
    pop = _open_selectbox_popover(page)

    # Try role=option first if available
    try:
        opt = page.get_by_role("option", name=re.compile(regex_pattern, re.I)).first
        opt.wait_for(timeout=1500)
        opt.click()
        return
    except Exception:
        pass

    # Fallback: click by text inside popover/container…
    try:
        pop.get_by_text(re.compile(regex_pattern, re.I)).first.wait_for(timeout=2500)
        pop.get_by_text(re.compile(regex_pattern, re.I)).first.click()
        return
    except Exception:
        pass

    # Last resort: click by text anywhere on the page
    page.get_by_text(re.compile(regex_pattern, re.I)).first.wait_for(timeout=3000)
    page.get_by_text(re.compile(regex_pattern, re.I)).first.click()


def wait_for_heading(page: Page, names):
    if isinstance(names, str):
        names = [names]
    for name in names:
        if _wait_heading_or_sentinel(page, name, timeout_ms=12000):
            return
    raise AssertionError(f"None of the headings matched: {names}")
