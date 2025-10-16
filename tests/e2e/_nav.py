# tests/e2e/_nav.py
import re
import time
from typing import Iterable, Tuple, Union, List, Optional
from pathlib import Path
from playwright.sync_api import Page, expect

# Base URL is still overridden by pytest-base-url if configured.
BASE_URL = "http://127.0.0.1:8501"

# Stable label->slug mapping for direct deep-link
LABEL_SLUG = {
    "Control Center": "control-center",
    "Option Chain": "option-chain",
    "Diagnostics / Logs": "diagnostics",   # keep if you have this route
}

def _slugify(label: str) -> str:
    return LABEL_SLUG.get(label, re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"))

def _rx(label: str):
    return re.compile(rf"^{re.escape(label)}$", re.IGNORECASE)

def _shoot(page: Page, name: str) -> None:
    try:
        out = Path("playwright-artifacts")
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f"{name}.png"), full_page=True)
    except Exception:
        pass  # best-effort

def _wait_for_popover(page: Page, timeout_ms: int = 8000):
    """
    Wait for a select popover across Streamlit/BaseWeb variants.
    """
    loc = page.locator(
        '[role="listbox"], [data-baseweb="menu"], div[role="menu"], div[aria-expanded="true"]'
    ).first
    loc.wait_for(state="visible", timeout=timeout_ms)
    return loc

def _click_nav_toggle(page: Page) -> None:
    """
    Click whichever element acts as the nav selectbox toggle.
    Order: sidebar combobox -> any combobox -> button[aria-haspopup=listbox] -> label 'Navigate'
    """
    # 1) Sidebar combobox if present
    try:
        combo = page.locator('[data-testid="stSidebar"] [role="combobox"]').first
        combo.wait_for(state="visible", timeout=3000)
        combo.click()
        return
    except Exception:
        pass

    # 2) Any visible combobox
    try:
        combo_any = page.get_by_role("combobox").first
        combo_any.wait_for(state="visible", timeout=3000)
        combo_any.click()
        return
    except Exception:
        pass

    # 3) Button with listbox popup
    try:
        btn = page.locator('button[aria-haspopup="listbox"]').first
        btn.wait_for(state="visible", timeout=3000)
        btn.click()
        return
    except Exception:
        pass

    # 4) Label text (fallback)
    try:
        page.get_by_text(re.compile(r"^Navigate$", re.I)).first.click()
        return
    except Exception:
        pass

    raise AssertionError("Could not locate nav toggle (combobox/button/label).")

def _open_selectbox_popover(page: Page):
    """
    Open the nav popover with retries, tolerant of slow UI.
    """
    last_err: Optional[Exception] = None
    for attempt in range(4):
        try:
            _click_nav_toggle(page)
            return _wait_for_popover(page, timeout_ms=6000 if attempt == 0 else 9000)
        except Exception as e:
            last_err = e
            # Retry by clicking again or using keyboard to nudge open
            try:
                page.keyboard.press("Enter")
                time.sleep(0.15)
            except Exception:
                pass
            time.sleep(0.2)
    _shoot(page, "nav-popover-timeout")
    raise AssertionError(f"Failed to open nav popover: {last_err}")

def open_nav_and_select(page: Page, label_or_regex: Union[str, re.Pattern, Tuple[str, ...]]):
    """
    Opens the nav dropdown and selects an option.
    Accepts exact label string, compiled regex, or tuple of choices.
    """
    if isinstance(label_or_regex, tuple):
        names = [ _rx(l) if isinstance(l, str) else l for l in label_or_regex ]
    elif isinstance(label_or_regex, str):
        names = [ _rx(label_or_regex) ]
    else:
        names = [ label_or_regex ]

    menu = _open_selectbox_popover(page)

    # Preferred: ARIA options
    for pat in names:
        try:
            opt = page.get_by_role("option", name=pat).first
            opt.wait_for(state="visible", timeout=5000)
            opt.click()
            return
        except Exception:
            continue

    # Fallback: text-based selection inside the popover container
    for pat in names:
        try:
            match = menu.get_by_text(pat).first
            match.wait_for(state="visible", timeout=5000)
            match.click()
            return
        except Exception:
            continue

    _shoot(page, "nav-select-miss")
    raise AssertionError(f"Nav option not found for any of: {names}")

def wait_for_heading(page: Page, names: Union[str, Iterable[str]], timeout_ms: int = 15000):
    """
    Wait for a visible heading whose accessible name matches one of `names`.
    """
    if isinstance(names, str):
        names = [names]
    pats = [ _rx(n) for n in names ]
    end = time.time() + (timeout_ms / 1000.0)
    last_err = None
    while time.time() < end:
        for pat in pats:
            try:
                h = page.get_by_role("heading", name=pat).first
                h.wait_for(state="visible", timeout=1000)
                expect(h).to_be_visible()
                return
            except Exception as e:
                last_err = e
        time.sleep(0.2)
    _shoot(page, "heading-timeout")
    raise AssertionError(f"Heading not found for any of {list(names)}; last error: {last_err}")

def goto_page(page: Page, label: str):
    """
    Robust navigation to a page by its human label:
      1) Try direct deep-link via query param (fast path).
      2) If heading doesn't appear, fall back to opening the nav and selecting.
    """
    slug = _slugify(label)

    # 1) Deep-link fast path
    try:
        page.goto(f"{BASE_URL}/?page={slug}", wait_until="domcontentloaded", timeout=60000)
        wait_for_heading(page, (label,))
        return
    except Exception:
        # Keep going to UI-based selection
        pass

    # 2) UI fallback
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    open_nav_and_select(page, label)
    wait_for_heading(page, (label,))
