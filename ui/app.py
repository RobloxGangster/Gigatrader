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
from ui.pages.diagnostics_logs import render as render_diagnostics_logs
from ui.router import (
    PAGES,
    PageDef,
    all_labels,
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
        slug="diagnostics",
        label="Diagnostics / Logs",
        render=lambda: render_diagnostics_logs(api, state),
        headings=("Diagnostics / Logs", "Diagnostics", "Logs & Pacing", "Logs"),
    )


DEFAULT_SLUG = "control-center"


def _page_from_query_or_default() -> PageDef:
    """Resolve the current page from query params, falling back gracefully."""

    slug: str = DEFAULT_SLUG
    try:
        qp = st.query_params  # type: ignore[attr-defined]
        raw = qp.get("page")
    except Exception:
        legacy_qp = st.experimental_get_query_params()  # type: ignore[attr-defined]
        raw = legacy_qp.get("page")
    if isinstance(raw, list):
        slug = raw[0] if raw else DEFAULT_SLUG
    elif raw:
        slug = raw
    slug = str(slug or DEFAULT_SLUG).strip().lower()
    page = PAGES.get(slug)
    if page:
        return page
    fallback = next(iter(PAGES.values()), None)
    if fallback is None:  # pragma: no cover - sanity guard
        raise RuntimeError("No pages registered")
    return fallback


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

    _, qp_obj, has_new_api = _get_query_params_state()
    current_page = _page_from_query_or_default()
    current_slug = current_page.slug

    labels = all_labels()
    current_label = current_page.label

    try:
        current_index = labels.index(current_label)
    except ValueError:
        current_index = 0
        if labels:
            current_label = labels[current_index]
            current_slug = label_to_slug(current_label)

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
        st.markdown('<div data-testid="nav-select"></div>', unsafe_allow_html=True)
        choice = st.selectbox(
            "Navigation",
            labels,
            index=current_index,
            key="nav_select",
            label_visibility="collapsed",
            help="Jump to a page",
        )

        st.markdown(
            """
            <script>
            (function() {
              const doc = window.parent.document;
              const navRoot = doc.querySelector('div[data-testid="nav-root"]');
              if (!navRoot) { return; }
              const selectButton = navRoot.parentElement?.querySelector('div[data-baseweb="select"] button');
              if (selectButton) {
                selectButton.setAttribute('data-testid', 'nav-select');
                selectButton.setAttribute('aria-haspopup', 'listbox');
              }
            })();
            </script>
            """,
            unsafe_allow_html=True,
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

                base = api_base_url().rstrip("/")
                requests.post(f"{base}/paper/start", timeout=1)
            except Exception:
                pass

    current_page.render()


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
