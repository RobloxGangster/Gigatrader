from __future__ import annotations

# Must be first so absolute `ui.*` imports work regardless of launch dir.
try:
    from ui._bootstrap import ROOT  # noqa: F401
except Exception:  # pragma: no cover - defensive bootstrap
    import sys
    from pathlib import Path

    _ROOT = Path(__file__).resolve().parents[1]
    _s = str(_ROOT)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from typing import Dict, Optional

import streamlit as st

from ui.lib.api_client import ApiClient, discover_base_url
from ui.lib.nav import (
    NAV_ITEMS,
    default_slug,
    dispatch_render,
    find_by_slug,
    resolve_renderer,
)


def _read_query_params() -> Dict[str, str]:
    try:
        return dict(st.query_params)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - Streamlit < 1.30 fallback
        params = st.experimental_get_query_params()
        return {k: v[0] if isinstance(v, list) and v else v for k, v in params.items()}


def _set_query_slug(slug: str) -> None:
    try:
        st.query_params["page"] = slug
    except Exception:  # pragma: no cover - legacy fallback
        st.experimental_set_query_params(page=slug)


def _stored_slug() -> Optional[str]:
    value = st.session_state.get("nav.slug")
    return str(value) if isinstance(value, str) else None


def _initial_item() -> Dict[str, str]:
    params = _read_query_params()
    raw_slug = params.get("page")
    if raw_slug:
        item = find_by_slug(raw_slug)
        if item:
            return item
    stored = _stored_slug()
    if stored:
        item = find_by_slug(stored)
        if item:
            return item
    return find_by_slug(default_slug()) or NAV_ITEMS[0]


def main() -> None:
    st.set_page_config(
        page_title="Gigatrader",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
    <style>
      /* Hide Streamlit's auto-generated sidebar page nav to avoid duplication */
      section[data-testid="stSidebarNav"] { display: none !important; }
    </style>
    """,
        unsafe_allow_html=True,
    )

    current_item = _initial_item()
    slug = current_item["slug"]
    st.session_state["nav.slug"] = slug

    labels = [item["label"] for item in NAV_ITEMS]
    current_index = next((i for i, item in enumerate(NAV_ITEMS) if item["slug"] == slug), 0)

    selection = st.selectbox(
        "Navigation",
        labels,
        index=current_index,
        key="nav.select",
        help="Jump between Gigatrader pages.",
    )

    selected_item = next(item for item in NAV_ITEMS if item["label"] == selection)
    if selected_item["slug"] != slug:
        slug = selected_item["slug"]
        st.session_state["nav.slug"] = slug
        _set_query_slug(slug)
        current_item = selected_item
    else:
        params = _read_query_params()
        if params.get("page") != slug:
            _set_query_slug(slug)

    resolved_api = discover_base_url()
    client = ApiClient()
    st.caption(f"Resolved API: {resolved_api}")
    st.session_state.setdefault("api.base_url", client.base())

    renderer = resolve_renderer(current_item)
    dispatch_render(renderer)


if __name__ == "__main__":
    main()
