from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from ui.pages.backtest_reports import render as render_backtest_reports
from ui.pages.control_center import render as render_control_center
from ui.pages.option_chain import render as render_option_chain
from ui.pages.research import render as render_research
from ui.pages.strategy_tuning import render as render_strategy_tuning
from ui.pages.diagnostics import render as render_diagnostics
from ui.router import (
    PAGES,
    all_labels,
    get_page_from_query_params,
    label_to_slug,
    register_page,
)
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state
from ui.utils.runtime import get_runtime_flags


def _register_pages(api: object, state: AppSessionState) -> None:
    """Populate the global page registry with Streamlit renderers."""

    PAGES.clear()

    register_page(
        slug="control-center",
        label="Control Center",
        render=lambda: render_control_center(api, state),
        headings=("Control Center",),
    )
    register_page(
        slug="option-chain",
        label="Option Chain",
        render=lambda: render_option_chain(api, state),
        headings=("Option Chain",),
    )
    register_page(
        slug="research",
        label="Research",
        render=lambda: render_research(api, state),
        headings=("Research",),
    )
    register_page(
        slug="strategy-tuning",
        label="Strategy Tuning",
        render=lambda: render_strategy_tuning(api, state),
        headings=("Strategy Tuning",),
    )
    register_page(
        slug="backtest-reports",
        label="Backtest Reports",
        render=lambda: render_backtest_reports(api, state),
        headings=("Backtest Reports",),
    )
    register_page(
        slug="diagnostics-logs",
        label="Diagnostics / Logs",
        render=lambda: render_diagnostics(api, state),
        headings=("Diagnostics / Logs", "Diagnostics", "Logs & Pacing", "Logs"),
    )


def _get_query_params_state() -> tuple[dict, object | None, bool]:
    """Return current query params, backing object, and API availability flag."""

    try:
        qp_obj = st.query_params  # type: ignore[attr-defined]
        return dict(qp_obj), qp_obj, True
    except Exception:
        qp_dict = st.experimental_get_query_params()  # type: ignore[attr-defined]
        return qp_dict, None, False


def _update_page_query_param(slug: str, qp_obj: object | None, has_new_api: bool) -> None:
    """Update the ?page=<slug> query parameter without clobbering others."""

    if has_new_api and qp_obj is not None:
        try:
            qp_obj["page"] = slug  # type: ignore[index]
        except Exception:
            pass
        return

    existing = st.experimental_get_query_params()  # type: ignore[attr-defined]
    existing["page"] = slug
    st.experimental_set_query_params(**existing)  # type: ignore[attr-defined]


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    st.set_page_config(page_title="Gigatrader", layout="wide")
    _hide_streamlit_sidebar_nav()

    st.title("Gigatrader")

    state: AppSessionState = init_session_state()
    api = get_backend()

    flags = get_runtime_flags(api)
    st.session_state["__mock_mode__"] = flags.mock_mode

    _register_pages(api, state)

    if not PAGES:
        raise RuntimeError("No pages registered")

    qp_dict, qp_obj, has_new_api = _get_query_params_state()
    current_slug = get_page_from_query_params(qp_dict, default_slug="control-center")
    if current_slug not in PAGES:
        current_slug = "control-center"

    labels = all_labels()
    try:
        current_label = PAGES[current_slug].label
    except KeyError:
        # Fallback to the first registered page if something goes wrong.
        current_slug = next(iter(PAGES))
        current_label = PAGES[current_slug].label

    try:
        current_index = labels.index(current_label)
    except ValueError:
        current_index = 0
        current_slug = next(iter(PAGES))
        current_label = labels[current_index]

    st.markdown(
        """
        <style>
        div[data-baseweb="menu"] { display: block !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown('<div data-testid="nav-root"></div>', unsafe_allow_html=True)
        choice = st.selectbox(
            "Navigate",
            labels,
            index=current_index,
            key="nav_select",
            label_visibility="collapsed",
            help="Jump to a page",
        )

    if choice != current_label:
        try:
            new_slug = label_to_slug(choice)
        except KeyError:
            new_slug = current_slug
        if new_slug != current_slug:
            _update_page_query_param(new_slug, qp_obj, has_new_api)
            st.rerun()

    current_page = PAGES[current_slug]

    st.markdown('<div data-testid="app-ready" style="display:none"></div>', unsafe_allow_html=True)

    _render_mode_badge(flags.mock_mode)
    st.write("")  # spacer

    st.sidebar.title("Gigatrader")
    if _is_mock_mode():
        st.sidebar.info("Mock mode is enabled")
    if not _is_mock_mode() and mock_mode():
        st.sidebar.info("Mock mode enabled – using fixture backend.")
    st.sidebar.caption(f"API: {api_base_url()}")
    st.sidebar.caption(f"Profile: {state.profile}")

    if _is_mock_mode():
        if st.button("Start Paper"):
            try:
                import requests

                base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
                requests.post(f"{base}/paper/start", timeout=1)
            except Exception:
                pass

    current_page.render()


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
