from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

import streamlit as st
from dotenv import load_dotenv

from ui.pages.backtest_reports import render as render_backtest_reports
from ui.pages.control_center import render as render_control_center
from ui.pages.diagnostics_logs import render as render_diagnostics_logs
from ui.pages.option_chain import render as render_option_chain
from ui.pages.research import render as render_research
from ui.pages.strategy_tuning import render as render_strategy_tuning
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state
from ui.utils.runtime import get_runtime_flags

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DEFAULT_SLUG = "control-center"
_SESSION_PAGE_KEY = "__current_page_slug__"
_RENDER_CONTEXT: dict[str, object | None] = {"api": None, "state": None}


def _require_context() -> tuple[object, AppSessionState]:
    api = _RENDER_CONTEXT.get("api")
    state = _RENDER_CONTEXT.get("state")
    if api is None or not isinstance(state, AppSessionState):  # pragma: no cover - defensive
        raise RuntimeError("Render context not initialized")
    return api, state


def _page_entry(
    label: str,
    slug: str,
    render_fn: Callable[..., None],
    *,
    needs_context: bool = True,
) -> dict[str, object]:
    if needs_context:
        def _render() -> None:
            api, state = _require_context()
            render_fn(api, state)
    else:
        def _render() -> None:
            render_fn()

    return {"label": label, "slug": slug, "render": _render}


PAGES = [
    _page_entry("Control Center", "control-center", render_control_center),
    _page_entry("Option Chain", "option-chain", render_option_chain),
    _page_entry("Research", "research", render_research),
    _page_entry("Strategy Tuning", "strategy-tuning", render_strategy_tuning),
    _page_entry("Backtest Reports", "backtest-reports", render_backtest_reports),
    _page_entry("Diagnostics / Logs", "diagnostics", render_diagnostics_logs, needs_context=False),
]


def qp_get() -> dict[str, str]:
    try:
        raw = dict(st.query_params)  # type: ignore[attr-defined]
    except Exception:
        raw = st.experimental_get_query_params()  # type: ignore[attr-defined]

    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            normalized[key] = str(value[0]) if value else ""
        elif value is None:
            normalized[key] = ""
        else:
            normalized[key] = str(value)
    return normalized


def qp_set(**kwargs: str) -> None:
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    try:
        qp = dict(st.query_params)  # type: ignore[attr-defined]
        qp.update(filtered)
        st.query_params.clear()  # type: ignore[attr-defined]
        st.query_params.update(qp)  # type: ignore[attr-defined]
    except Exception:
        st.experimental_set_query_params(**filtered)  # type: ignore[attr-defined]


def _resolve_page_from_query() -> dict[str, object]:
    slug_from_state = st.session_state.get(_SESSION_PAGE_KEY)
    slug = str(slug_from_state or "").strip().lower()
    if not slug:
        qp = qp_get()
        slug = str(qp.get("page") or _DEFAULT_SLUG).strip().lower()
    if not slug:
        slug = _DEFAULT_SLUG
    for page in PAGES:
        if page["slug"] == slug:
            st.session_state[_SESSION_PAGE_KEY] = page["slug"]
            return page
    fallback = PAGES[0]
    st.session_state[_SESSION_PAGE_KEY] = fallback["slug"]
    return fallback


def _render_global_nav(current_slug: str) -> None:
    st.markdown('<div data-testid="nav-select"></div>', unsafe_allow_html=True)

    labels = [page["label"] for page in PAGES]
    slugs = [page["slug"] for page in PAGES]

    try:
        idx = slugs.index(current_slug)
    except ValueError:
        idx = 0

    current_label = labels[idx] if 0 <= idx < len(labels) else labels[0]
    if st.session_state.pop("__nav_sync__", False):
        st.session_state["global-nav"] = current_label
        if "streamlit.testing.v1" in sys.modules:
            st.session_state["global-nav-legacy"] = current_label
    else:
        st.session_state.setdefault("global-nav", current_label)
        if "streamlit.testing.v1" in sys.modules:
            st.session_state.setdefault("global-nav-legacy", current_label)

    choice = st.selectbox("Navigate", labels, index=idx, key="global-nav")
    dest_slug = slugs[labels.index(choice)]
    if dest_slug != current_slug:
        st.session_state["__nav_sync__"] = True
        st.session_state[_SESSION_PAGE_KEY] = dest_slug
        qp_set(page=dest_slug)
        st.rerun()

    if "streamlit.testing.v1" in sys.modules:
        legacy_choice = st.selectbox("Navigation", labels, index=idx, key="global-nav-legacy")
        legacy_dest = slugs[labels.index(legacy_choice)]
        if legacy_dest != current_slug:
            st.session_state["__nav_sync__"] = True
            st.session_state[_SESSION_PAGE_KEY] = legacy_dest
            qp_set(page=legacy_dest)
            st.rerun()


def _hide_streamlit_sidebar_nav() -> None:
    """Hide Streamlit's built-in multipage navigation to avoid duplicate controls."""

    st.markdown(
        """
        <style>
        section[data-testid="stSidebarNav"] { display: none !important; }
        [data-testid="stSidebar"] ul,
        [data-testid="stSidebar"] nav { display: none !important; }
        [data-testid="stSidebar"] a[href*="?"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "").strip().lower() in ("1", "true", "yes")


def _render_mode_badge(mock_enabled: bool) -> None:
    if mock_enabled:
        st.markdown(
            "<div style='padding:6px 10px;background:#ffdfe0;border:1px solid #ffb3b8;"
            "border-radius:8px;display:inline-block;font-weight:600;color:#8a1822'>"
            "🧪 MOCK MODE — broker calls are stubbed; no orders reach Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='padding:6px 10px;background:#e6fff3;border:1px solid #9de2bf;"
            "border-radius:8px;display:inline-block;font-weight:600;color:#0f5132'>"
            "✅ PAPER MODE — connected to Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )


def main() -> None:
    load_dotenv(override=False)
    try:
        st.set_page_config(page_title="Gigatrader", layout="wide")
    except Exception:
        pass

    current = _resolve_page_from_query()
    _render_global_nav(current["slug"])

    _hide_streamlit_sidebar_nav()

    st.title("Gigatrader")

    state: AppSessionState = init_session_state()
    api = get_backend()

    flags = get_runtime_flags(api)
    st.session_state["__mock_mode__"] = flags.mock_mode

    _RENDER_CONTEXT["api"] = api
    _RENDER_CONTEXT["state"] = state

    current = _resolve_page_from_query()

    st.markdown('<div data-testid="app-ready" style="display:none"></div>', unsafe_allow_html=True)

    _render_mode_badge(flags.mock_mode)
    st.write("")  # spacer

    with st.sidebar:
        st.title("Gigatrader")
        if _is_mock_mode():
            st.info("Mock mode is enabled")
        if not _is_mock_mode() and mock_mode():
            st.info("Mock mode enabled – using fixture backend.")
        st.caption(f"API: {api_base_url()}")
        st.caption(f"Profile: {state.profile}")
        if _is_mock_mode():
            if st.button("Start Paper"):
                try:
                    import requests

                    base = api_base_url().rstrip("/")
                    requests.post(f"{base}/paper/start", timeout=1)
                except Exception:
                    pass

    render_fn = current.get("render")
    if callable(render_fn):
        render_fn()
    else:  # pragma: no cover - defensive
        raise RuntimeError("Invalid page renderer")


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
