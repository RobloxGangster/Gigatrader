import re
import time
from typing import Iterable, Tuple, Union

from playwright.sync_api import Page, expect

BASE_URL = "http://127.0.0.1:8501"  # overridden by pytest-base-url if configured

LabelMatcher = Union[str, re.Pattern]


def _regex(label: str):
    return re.compile(rf"^{re.escape(label)}$", re.IGNORECASE)


def _open_selectbox_popover(page: Page):
    """
    Click the first visible nav combobox/selectbox and wait for its popover.
    Works across Streamlit/BaseWeb variants.
    """
    combo = page.get_by_role("combobox").first
    combo.wait_for(state="visible", timeout=15_000)
    combo.click()

    menu = page.locator('[role="listbox"], [data-baseweb="menu"], div[aria-expanded="true"]').first
    menu.wait_for(state="visible", timeout=10_000)
    return menu


def open_nav_and_select(page: Page, label_or_regex: Union[LabelMatcher, Tuple[LabelMatcher, ...]]):
    """
    Opens the nav dropdown and selects an option.
    Accepts exact label string, compiled regex, or a tuple of labels (any match).
    """
    if isinstance(label_or_regex, tuple):
        names = [_regex(l) if isinstance(l, str) else l for l in label_or_regex]
    elif isinstance(label_or_regex, str):
        names = [_regex(label_or_regex)]
    else:
        names = [label_or_regex]

    menu = _open_selectbox_popover(page)

    for pat in names:
        try:
            opt = page.get_by_role("option", name=pat).first
            opt.wait_for(timeout=10_000)
            opt.click()
            return
        except Exception:
            continue

    for pat in names:
        try:
            opt2 = menu.get_by_text(pat).first
            opt2.wait_for(timeout=10_000)
            opt2.click()
            return
        except Exception:
            continue

    raise AssertionError(f"Nav option not found for any of: {names}")


def wait_for_heading(page: Page, names: Union[str, Iterable[str]], timeout_ms: int = 15_000):
    """
    Waits for a visible heading whose accessible name matches one of `names`.
    """
    if isinstance(names, str):
        names = [names]
    compiled = [_regex(n) for n in names]

    end = time.time() + (timeout_ms / 1000.0)
    last_err = None
    while time.time() < end:
        for pat in compiled:
            try:
                h = page.get_by_role("heading", name=pat).first
                h.wait_for(state="visible", timeout=1_000)
                expect(h).to_be_visible()
                return
            except Exception as e:
                last_err = e
        time.sleep(0.2)
    raise AssertionError(f"Heading not found for any of {list(names)}; last error: {last_err}")


def goto_page(page: Page, label: str):
    """
    Open the nav dropdown and select the given label. Assumes sidebar selectbox is present.
    """
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    open_nav_and_select(page, label)
    wait_for_heading(page, (label,))
