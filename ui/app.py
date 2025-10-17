from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Iterable, Tuple

import streamlit as st
from dotenv import load_dotenv

from ui.pages import (
    backtest_reports,
    control_center,
    diagnostics_logs,
    option_chain,
    research,
    strategy_tuning,
)
from ui.router import Page, render_nav_and_route, slugify
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state
from ui.utils.runtime import get_runtime_flags

def _page_definitions() -> Iterable[Tuple[str, object]]:
    return (
        ("Control Center", control_center),
        ("Option Chain", option_chain),
        ("Research", research),
        ("Strategy Tuning", strategy_tuning),
        ("Backtest Reports", backtest_reports),
        ("Diagnostics / Logs", diagnostics_logs),
    )


def _build_pages(api: object, state: AppSessionState) -> Dict[str, Page]:
    pages: Dict[str, Page] = {}
    for label, module in _page_definitions():
        render_fn = getattr(module, "render", None)
        if not callable(render_fn):
            continue
        page = Page(
            label=label,
            slug=slugify(label),
            render=lambda render_fn=render_fn, api=api, state=state: render_fn(api, state),
        )
        pages[page.slug] = page
    return pages

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

    pages = _build_pages(api, state)

    st.markdown('<div data-testid="nav-root"></div>', unsafe_allow_html=True)
    selected_page = render_nav_and_route(pages, default_label="Control Center", auto_render=False)

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

    selected_page.render()


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
