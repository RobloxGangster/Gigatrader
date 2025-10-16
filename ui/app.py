from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict

import streamlit as st
from dotenv import load_dotenv

from ui.pages import (
    backtest_reports,
    control_center,
    logs_pacing,
    option_chain,
    research,
    strategy_tuning,
)
from ui.services.backend import get_backend
from ui.services.config import api_base_url, mock_mode
from ui.state import AppSessionState, init_session_state
from ui.utils.runtime import get_runtime_flags

PAGE_MAP: Dict[str, Callable[[Any, Any], None]] = {
    "Control Center": control_center,
    "Option Chain": option_chain,
    "Research": research,
    "Strategy Tuning": strategy_tuning,
    "Backtest Reports": backtest_reports,
    "Diagnostics / Logs": logs_pacing,
}


def to_slug(label: str) -> str:
    return label.lower().replace(" ", "-").replace("/", "").replace("&", "and")


SLUG_TO_LABEL = {to_slug(lbl): lbl for lbl in PAGE_MAP.keys()}

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

    try:
        qp = st.query_params  # type: ignore[attr-defined]
        qp_get = qp.get
        qp_set = qp.update
    except Exception:
        qp = None
        qp_get = lambda key, default=None: st.experimental_get_query_params().get(key, [default])[0]
        qp_set = lambda d: st.experimental_set_query_params(**d)

    requested = qp_get("page", None)
    if requested:
        req = requested if isinstance(requested, str) else (requested[0] if requested else None)
        normalized = SLUG_TO_LABEL.get(to_slug(req), None) or (req if req in PAGE_MAP else None)
    else:
        normalized = None

    st.markdown('<div data-testid="nav-root"></div>', unsafe_allow_html=True)
    page_labels = list(PAGE_MAP.keys())

    default_index = page_labels.index(normalized) if normalized in page_labels else 0
    selection = st.selectbox(
        "Navigation",
        page_labels,
        index=default_index,
        key="nav_select",
        help="Jump to any page",
    )

    qp_set({"page": to_slug(selection)})

    st.markdown('<div data-testid="app-ready" style="display:none"></div>', unsafe_allow_html=True)

    state: AppSessionState = init_session_state()
    api = get_backend()

    flags = get_runtime_flags(api)
    st.session_state["__mock_mode__"] = flags.mock_mode

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

    page_mod = PAGE_MAP.get(selection, control_center)
    if page_mod and hasattr(page_mod, "render"):
        page_mod.render(api, state)
    else:
        st.error(f"Page '{selection}' is not available.")


if __name__ == "__main__":  # pragma: no cover - executed by Streamlit runtime
    main()
