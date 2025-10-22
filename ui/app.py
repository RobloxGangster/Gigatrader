from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

import streamlit as st
from dotenv import load_dotenv

# Import page renderers
from ui.pages.control_center import render as _render_control_center
from ui.pages.option_chain import render as _render_option_chain
try:
    from ui.pages.diagnostics_logs import render as render_diagnostics_logs
except Exception:
    # Fallback if legacy path/file name differs; adjust import if needed.
    from ui.pages.diagnostics import render as render_diagnostics_logs  # type: ignore

from ui.pages.backtest_reports import render as _render_backtest_reports
from ui.pages.research import render as _render_research
from ui.pages.strategy_tuning import render as _render_strategy_tuning
from ui.services.backend import BrokerAPI, get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state
from ui.utils.runtime import RuntimeFlags, get_runtime_flags

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- Page registry (keep labels stable; slug 'diagnostics' is REQUIRED) ----

def _wrap_page(render_fn, needs_context: bool = True):
    if not needs_context:
        return render_fn

    def _wrapped() -> None:
        api, state = _require_context()
        render_fn(api, state)

    return _wrapped


PAGES: list[Dict[str, Any]] = [
    {"label": "Control Center", "slug": "control-center", "render": _wrap_page(_render_control_center)},
    {"label": "Option Chain", "slug": "option-chain", "render": _wrap_page(_render_option_chain)},
    {"label": "Diagnostics / Logs", "slug": "diagnostics", "render": _wrap_page(render_diagnostics_logs, needs_context=False)},
]

# Additional pages remain available via the same registry for compatibility.
PAGES.extend(
    [
        {"label": "Research", "slug": "research", "render": _wrap_page(_render_research)},
        {"label": "Strategy Tuning", "slug": "strategy-tuning", "render": _wrap_page(_render_strategy_tuning)},
        {"label": "Backtest Reports", "slug": "backtest-reports", "render": _wrap_page(_render_backtest_reports)},
    ]
)

# ---- Compat shims for query params (new + legacy) ----

def qp_get() -> Dict[str, Any]:
    try:
        return dict(st.query_params)
    except Exception:
        raw = st.experimental_get_query_params()
        return {k: (v[0] if isinstance(v, list) and v else v) for k, v in raw.items()}


def qp_set(**kwargs) -> None:
    try:
        st.query_params.clear()
        st.query_params.update(kwargs)
    except Exception:
        st.experimental_set_query_params(**kwargs)


def _resolve_page_from_query() -> Dict[str, Any]:
    qp = qp_get()
    slug = (qp.get("page") or "").strip().lower()
    # Accept a few legacy aliases, but normalize to 'diagnostics'
    if slug in {"diagnostics", "diagnostics-logs", "logs", "log"}:
        slug = "diagnostics"
    if not slug:
        slug = "control-center"
    for page in PAGES:
        if page["slug"] == slug:
            st.session_state["__current_page_slug__"] = slug
            return page
    fallback = PAGES[0]
    st.session_state["__current_page_slug__"] = fallback["slug"]
    return fallback


def _render_global_nav(current_slug: str) -> None:
    # Marker to help tests anchor near the nav
    st.markdown('<div data-testid="nav-select"></div>', unsafe_allow_html=True)
    labels = [page["label"] for page in PAGES]
    slugs = [page["slug"] for page in PAGES]
    try:
        idx = slugs.index(current_slug)
    except ValueError:
        idx = 0
    # MUST be visible and labeled exactly "Navigate"
    choice = st.selectbox(
        "Navigate",
        labels,
        index=idx,
        key="global-nav-select",
        label_visibility="visible",
        help="Use this to switch pages",
    )
    dest_slug = slugs[labels.index(choice)]
    if dest_slug != current_slug:
        qp_set(page=dest_slug)
        st.rerun()


_RENDER_CONTEXT: dict[str, object | None] = {"api": None, "state": None}


def _require_context() -> tuple[BrokerAPI, AppSessionState]:
    api = _RENDER_CONTEXT.get("api")
    state = _RENDER_CONTEXT.get("state")
    if api is None or not isinstance(state, AppSessionState):  # pragma: no cover - defensive
        raise RuntimeError("Render context not initialized")
    return api, state


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
            "<div style='padding:6px 10px;background:#ffdfe0;border:1px solid #ffb3b8;'"
            "border-radius:8px;display:inline-block;font-weight:600;color:#8a1822'>"
            "🧪 MOCK MODE — broker calls are stubbed; no orders reach Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='padding:6px 10px;background:#e6fff3;border:1px solid #9de2bf;'"
            "border-radius:8px;display:inline-block;font-weight:600;color:#0f5132'>"
            "✅ PAPER MODE — connected to Alpaca paper."
            "</div>",
            unsafe_allow_html=True,
        )


def _set_context(api: BrokerAPI, state: AppSessionState, flags: RuntimeFlags) -> None:
    _RENDER_CONTEXT["api"] = api
    _RENDER_CONTEXT["state"] = state
    st.session_state["__mock_mode__"] = flags.mock_mode


def main() -> None:
    load_dotenv(override=False)
    try:
        st.set_page_config(page_title="Gigatrader", layout="wide")
    except Exception:
        pass
    current = _resolve_page_from_query()
    # Render nav BEFORE any page content so it is interactable everywhere
    _render_global_nav(current["slug"])

    _hide_streamlit_sidebar_nav()

    st.title("Gigatrader")

    state: AppSessionState = init_session_state()
    api = get_backend()

    flags = get_runtime_flags(api)
    _set_context(api, state, flags)

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
