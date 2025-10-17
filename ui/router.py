from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping

import streamlit as st


@dataclass(frozen=True)
class Page:
    label: str
    slug: str
    render: Callable[[], None]


_SLUG_RX = re.compile(r"[^a-z0-9-]+")


def _slugify(label: str) -> str:
    """Generate a canonical slug for navigation and query params."""
    s = label.lower()
    s = s.replace("&", "and").replace("/", " ")
    s = re.sub(r"\s+", "-", s).strip("-")
    s = _SLUG_RX.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s


def slugify(label: str) -> str:
    """Public helper so callers do not need to import the private slugifier."""
    return _slugify(label)


def _normalize_query_params(qp: Mapping[str, object]) -> Dict[str, List[str]]:
    normalized: Dict[str, List[str]] = {}
    for key, value in qp.items():
        if isinstance(value, list):
            normalized[key] = [str(v) for v in value]
        else:
            normalized[key] = [str(value)]
    return normalized


def get_query_params() -> Dict[str, List[str]]:
    """Streamlit compatibility shim across versions."""
    try:
        qp = st.query_params  # type: ignore[attr-defined]
        return _normalize_query_params(qp)  # type: ignore[arg-type]
    except Exception:
        return st.experimental_get_query_params()  # type: ignore[attr-defined]


def set_query_params(**kwargs) -> None:
    try:
        qp = st.query_params  # type: ignore[attr-defined]
        qp.clear()
        for key, value in kwargs.items():
            qp[key] = value  # type: ignore[index]
    except Exception:
        st.experimental_set_query_params(**kwargs)  # type: ignore[attr-defined]


def resolve_page_slug(default_slug: str, pages: Dict[str, Page]) -> str:
    params = get_query_params()
    slug = params.get("page", [default_slug])[0]
    return slug if slug in pages else default_slug


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

    default_slug = _slugify(default_label)
    current_slug = resolve_page_slug(default_slug, pages)
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
    )

    target_label = choice
    target_slug = label_to_slug[target_label]

    if target_slug != current_slug:
        set_query_params(page=target_slug)
        st.rerun()
        # st.rerun() raises, but return a sensible default for type-checking.
        return pages[target_slug]

    params = get_query_params()
    current_param = params.get("page", [None])[0]
    if current_param != target_slug:
        set_query_params(page=target_slug)

    page = pages[target_slug]
    if auto_render:
        page.render()
    return page
