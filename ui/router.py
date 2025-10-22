"""Streamlit page registry and helpers for navigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple


@dataclass(frozen=True)
class PageDef:
    """Metadata for a registered Streamlit page."""

    slug: str
    label: str
    render: Callable[[], None]
    headings: Tuple[str, ...]


# Global registry populated at runtime by the app entrypoint.
PAGES: Dict[str, PageDef] = {}


def register_page(
    slug: str,
    label: str,
    render: Callable[[], None],
    headings: List[str] | Tuple[str, ...],
) -> PageDef:
    """Register a page definition using an explicit slug and label."""

    page_def = PageDef(slug=slug, label=label, render=render, headings=tuple(headings))
    PAGES[slug] = page_def
    return page_def


def all_labels() -> List[str]:
    """Return the ordered list of page labels currently registered."""

    return [page.label for page in PAGES.values()]


def label_to_slug(label: str) -> str:
    """Resolve a human-readable label back to the canonical slug."""

    for slug, page in PAGES.items():
        if page.label.lower() == label.lower():
            return slug
    if label in PAGES:
        # Already a slug – allow callers that pass through the slug directly.
        return label
    raise KeyError(label)


def get_page_from_query_params(qp: dict, default_slug: str) -> str:
    """Determine the requested page slug from Streamlit query parameters."""

    raw = qp.get("page", None)
    if raw is None or (isinstance(raw, list) and not raw):
        return default_slug
    if isinstance(raw, list):
        raw = raw[0]
    slug = str(raw).strip().lower()
    legacy_map = {
        "diagnostics-logs": "diagnostics",
    }
    slug = legacy_map.get(slug, slug)
    return slug if slug in PAGES else default_slug

