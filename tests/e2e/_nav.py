import re
import time
from pathlib import Path
from typing import Iterable, Tuple, Union, Optional, List

from playwright.sync_api import Page, expect

DIAG_READY_TEXT = re.compile(
    r"(Diagnostics complete|All checks passed|Completed diagnostics|done)", re.I
)

BASE_URL = "http://127.0.0.1:8501"

# Stable label->slug mapping for deep-linking
LABEL_SLUG = {
    "Control Center": "control-center",
    "Option Chain": "option-chain",
    "Diagnostics / Logs": "diagnostics",
}

# Accept multiple headings per page (Streamlit / copy varies)
LABEL_HEADINGS = {
    "Control Center": ("Control Center",),
    "Option Chain": ("Option Chain",),
    "Diagnostics / Logs": (
        "Diagnostics / Logs",
        "Diagnostics",
        "Logs & Pacing",
        "Logs",
    ),
}


def _slugify(label: str) -> str:
    return LABEL_SLUG.get(label, re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"))


def _rx(s: str):
    return re.compile(rf"^{re.escape(s)}$", re.IGNORECASE)


def _shoot(page: Page, name: str, hint: str = "") -> None:
    try:
        out = Path("playwright-artifacts")
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f"{name}.png"), full_page=True)
        if hint:
            (out / f"{name}.txt").write_text(hint, encoding="utf-8")
    except Exception:
        pass


def _wait_for_popover(page: Page, timeout_ms: int = 9000):
    """
    Wait for a select/menu popover across Streamlit/BaseWeb variants.
    """
    pop = page.locator(
        '[role="listbox"], [data-baseweb="menu"], [role="menu"], div[aria-expanded="true"]'
    ).first
    pop.wait_for(state="visible", timeout=timeout_ms)
    return pop


def _click_nav_toggle(page: Page) -> None:
    """
    Click whatever acts as the nav toggle:
    - Sidebar combobox
    - Header combobox
    - Any combobox
    - Button with aria-haspopup=listbox/menu
    - Visible 'Navigate' text
    """
    selectors = [
        '[data-testid="stSidebar"] [role="combobox"]',
        '[data-testid="stHeader"] [role="combobox"]',
        '[role="combobox"]',
        'button[aria-haspopup="listbox"]',
        'button[aria-haspopup="menu"]',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=2500)
            el.click()
            return
        except Exception:
            continue
    # Text fallback
    try:
        page.get_by_text(re.compile(r"\bNavigate\b", re.I)).first.click()
        return
    except Exception:
        pass
    raise AssertionError("Nav toggle not found (combobox/button/label).")


def _open_selectbox_popover(page: Page):
    """
    Open popover with retries + keyboard nudges.
    """
    last_err: Optional[Exception] = None
    for attempt in range(5):
        try:
            _click_nav_toggle(page)
            return _wait_for_popover(page, timeout_ms=7000 + attempt * 2000)
        except Exception as e:
            last_err = e
            # Keyboard nudges commonly open BaseWeb/Streamlit selects
            for key in ("Enter", "Space", "Alt+ArrowDown", "ArrowDown"):
                try:
                    page.keyboard.press(key)
                    time.sleep(0.2)
                except Exception:
                    pass
            time.sleep(0.3)
    _shoot(page, "nav-popover-timeout", hint=str(last_err))
    raise AssertionError(f"Failed to open nav popover: {last_err}")


def open_nav_and_select(page: Page, label_or_regex: Union[str, re.Pattern, Tuple[str, ...]]):
    """
    Open nav dropdown and select by exact label or regex. Retries across ARIA options and text.
    """
    targets: List[Union[str, re.Pattern]] = []
    if isinstance(label_or_regex, tuple):
        targets = [ _rx(t) if isinstance(t, str) else t for t in label_or_regex ]
    elif isinstance(label_or_regex, str):
        targets = [ _rx(label_or_regex) ]
    else:
        targets = [ label_or_regex ]

    menu = _open_selectbox_popover(page)

    # Prefer ARIA role=option
    for pat in targets:
        try:
            opt = page.get_by_role("option", name=pat).first
            opt.wait_for(state="visible", timeout=5000)
            opt.click()
            return
        except Exception:
            pass

    # Fallback: text inside the open menu container
    for pat in targets:
        try:
            match = menu.get_by_text(pat).first
            match.wait_for(state="visible", timeout=5000)
            match.click()
            return
        except Exception:
            pass

    _shoot(page, "nav-select-miss", hint=f"Targets: {targets}")
    raise AssertionError(f"Nav option not found for any of: {targets}")


def wait_for_heading(page: Page, names: Union[str, Iterable[str]], timeout_ms: int = 18000):
    """
    Wait for any acceptable heading to be visible (exact, case-insensitive).
    """
    if isinstance(names, str):
        names = (names,)
    pats = [ _rx(n) for n in names ]
    end = time.time() + timeout_ms / 1000
    last_err = None
    while time.time() < end:
        for pat in pats:
            try:
                h = page.get_by_role("heading", name=pat).first
                h.wait_for(state="visible", timeout=1200)
                expect(h).to_be_visible()
                return
            except Exception as e:
                last_err = e
        time.sleep(0.2)
    _shoot(page, "heading-timeout", hint=f"Acceptable: {list(names)}; last_err: {last_err}")
    raise AssertionError(f"Heading not found for any of {list(names)}")


def _acceptable_headings_for(label: str) -> Tuple[str, ...]:
    return LABEL_HEADINGS.get(label, (label,))


def goto_page(page: Page, label: str):
    """
    Robust nav:
      1) Deep-link to /?page=<slug>, accept multiple headings for the label.
      2) If headings don't appear, try UI dropdown selection.
      3) If UI popover fails, last-chance deep-link again before failing.
    """
    slug = _slugify(label)
    headings = _acceptable_headings_for(label)

    # 1) Deep-link first
    try:
        page.goto(f"{BASE_URL}/?page={slug}", wait_until="domcontentloaded", timeout=60000)
        wait_for_heading(page, headings)
        return
    except Exception:
        pass  # try UI fallback

    # 2) UI fallback
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        open_nav_and_select(page, label)
        wait_for_heading(page, headings)
        return
    except Exception as e:
        # 3) Last-chance deep-link before giving up
        try:
            page.goto(f"{BASE_URL}/?page={slug}", wait_until="domcontentloaded", timeout=60000)
            wait_for_heading(page, headings)
            return
        except Exception as ee:
            _shoot(page, "goto-page-failed", hint=f"UI error: {e}\nDeep-link retry: {ee}")
            raise


def click_run_diagnostics_if_present(page: Page, timeout_ms: int = 4000) -> bool:
    """
    Click the 'Run Diagnostics' button if it exists and is visible.
    Returns True if clicked, False if not found.
    """
    try:
        btn = page.get_by_role("button", name=re.compile(r"^Run Diagnostics$", re.I)).first
        btn.wait_for(state="visible", timeout=timeout_ms)
        try:
            btn.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            expect(btn).to_be_enabled(timeout=timeout_ms)
        except Exception:
            pass
        btn.click()
        return True
    except Exception:
        return False


def wait_for_diagnostics_ready(page: Page, timeout_ms: int = 25000) -> None:
    """
    Consider 'Diagnostics / Logs' ready if ANY of the following become visible:
      - Status text like 'Diagnostics complete'
      - A Logs/Pacing table or dataframe is visible
      - A heading that includes 'Logs', 'Logs & Pacing', or 'Diagnostics'
    Also tolerant of Streamlit/BaseWeb table variants.
    """
    end = time.time() + timeout_ms / 1000.0
    last_err: Optional[Exception] = None

    def any_visible() -> bool:
        nonlocal last_err

        # 1) Success text
        try:
            if page.get_by_text(DIAG_READY_TEXT).first.is_visible():
                return True
        except Exception:
            pass

        # 2) Table/dataframe variants
        candidates = [
            '[data-testid="stDataFrame"]',
            '[data-testid="stTable"]',
            '[role="table"]',
            '[role="grid"]',
            # Sometimes logs live under region with strong labels
            'section:has-text("Log")',
            'section:has-text("Logs")',
            'section:has-text("Pacing")',
        ]
        for sel in candidates:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.wait_for(state="visible", timeout=800)
                    return True
            except Exception as e:
                last_err = e

        # 3) Headings we consider acceptable for this page
        for h in LABEL_HEADINGS.get(
            "Diagnostics / Logs", ("Diagnostics / Logs", "Diagnostics", "Logs & Pacing", "Logs")
        ):
            try:
                if page.get_by_role("heading", name=_rx(h)).first.is_visible():
                    return True
            except Exception:
                pass

        return False

    while time.time() < end:
        try:
            if any_visible():
                return
        except Exception as e:
            last_err = e
        time.sleep(0.25)

    _shoot(page, "diagnostics-not-ready", hint=f"Waited {timeout_ms}ms; last_err={last_err}")
    raise AssertionError("Diagnostics page did not present ready indicators within timeout.")
