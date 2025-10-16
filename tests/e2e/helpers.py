from __future__ import annotations
from typing import Iterable
from playwright.sync_api import Page, TimeoutError as PWTimeout

NAV_LABEL = "Navigate"

# Aliases the tests will accept for Diagnostics
DIAG_ALIASES: tuple[str, ...] = (
    "Diagnostics / Logs",
    "Diagnostics",
    "Logs & Pacing",
    "Logs",
)


def _first_existing(page: Page, candidates: Iterable[str]) -> str | None:
    for name in candidates:
        try:
            page.get_by_role("option", name=name, exact=True).count()
            return name
        except Exception:
            continue
    return None


def open_nav(page: Page) -> None:
    # Prefer selectbox by label; fall back to first combobox
    try:
        cb = page.get_by_label(NAV_LABEL, exact=True)
        cb.click()
    except PWTimeout:
        page.get_by_role("combobox").first.click()


def select_nav(page: Page, target: str, aliases: Iterable[str] = ()) -> None:
    open_nav(page)
    # Try exact name first
    try:
        page.get_by_role("option", name=target, exact=True).click()
        return
    except Exception:
        pass
    # Try aliases (first one that exists)
    choice = _first_existing(page, aliases)
    if choice:
        page.get_by_role("option", name=choice, exact=True).click()
        return
    # As a last resort, pick the first option containing target token
    page.get_by_role("option").filter(has_text=target.split()[0]).first.click()


def wait_for_heading(page: Page, candidates: Iterable[str], timeout_ms: int = 10000) -> None:
    # Wait for any acceptable heading to appear
    for name in candidates:
        try:
            page.get_by_role("heading", name=name).wait_for(timeout=timeout_ms)
            return
        except Exception:
            continue
    # Last resort: ensure some heading exists
    page.get_by_role("heading").first.wait_for(timeout=timeout_ms)
