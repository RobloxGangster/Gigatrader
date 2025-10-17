from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List

import streamlit as st


@dataclass(frozen=True)
class Page:
    label: str
    slug: str
    render: Callable[[], None]


# Slugify used across app registration to ensure stable deep-links
_SLUG_RX = re.compile(r"[^a-z0-9-]+")


def slugify(label: str) -> str:
    s = label.lower()
    s = s.replace("&", "and")
    s = s.replace("/", " ")  # "Diagnostics / Logs" → "diagnostics-logs"
    s = re.sub(r"\s+", "-", s).strip("-")
    s = _SLUG_RX.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s


def _get_qp() -> Dict[str, List[str]]:
    try:
        # Streamlit v1.40+
        return dict(st.query_params)  # type: ignore[attr-defined]
    except Exception:
        return st.experimental_get_query_params()  # type: ignore[attr-defined]


def _set_qp(**kwargs) -> None:
    try:
        st.query_params.clear()  # type: ignore[attr-defined]
        for key, value in kwargs.items():  # type: ignore[attr-defined]
            st.query_params[key] = value
    except Exception:
        st.experimental_set_query_params(**kwargs)  # type: ignore[attr-defined]


def _alias(slug: str) -> str:
    """Map common aliases to the canonical Diagnostics slug to be lenient for tests."""

    diag = "diagnostics-logs"
    aliases = {
        "diagnostics": diag,
        "logs": diag,
        "logs-and-pacing": diag,
        diag: diag,
    }
    return aliases.get(slug, slug)


def resolve_slug(pages_by_slug: Dict[str, Page], default_slug: str) -> str:
    raw = _get_qp().get("page", [default_slug])[0]
    target = _alias(raw)
    if target in pages_by_slug:
        if target != raw:  # write back canonical slug
            _set_qp(page=target)
        return target
    # Unknown slug → snap to default and write it back
    _set_qp(page=default_slug)
    return default_slug


def resolve_page_slug(default_slug: str, pages: Dict[str, Page]) -> str:
    """Backward-compatible wrapper for legacy callers."""

    return resolve_slug(pages, default_slug)


def get_query_params() -> Dict[str, List[str]]:
    """Legacy public helper retained for compatibility."""

    return _get_qp()


def set_query_params(**kwargs) -> None:
    """Legacy public helper retained for compatibility."""

    _set_qp(**kwargs)


def render_nav_and_route(
    pages: Dict[str, Page],
    default_label: str,
    *,
    auto_render: bool = True,
) -> Page:
    if not pages:
        raise ValueError("pages cannot be empty")

    labels = [page.label for page in pages.values()]
    label_to_slug = {page.label: page.slug for page in pages.values()}
    slug_to_label = {page.slug: page.label for page in pages.values()}

    default_slug = slugify(default_label)
    current_slug = resolve_slug(pages, default_slug)
    current_label = slug_to_label.get(current_slug, default_label)

    try:
        current_index = labels.index(current_label)
    except ValueError:
        current_index = 0
        current_label = labels[current_index]
        current_slug = label_to_slug[current_label]

    choice = st.selectbox(
        "Navigate",
        labels,
        index=current_index,
        key="nav-select",
        help="Jump to a page",
    )
    if choice != current_label:
        _set_qp(page=label_to_slug[choice])
        st.rerun()

    with st.sidebar:
        choice_sidebar = st.selectbox(
            "Navigate",
            labels,
            index=current_index,
            key="nav-select-sidebar",
            help="Jump to a page (sidebar)",
        )
        if choice_sidebar != current_label:
            _set_qp(page=label_to_slug[choice_sidebar])
            st.rerun()

    page = pages[current_slug]
    if auto_render:
        page.render()
    return page
