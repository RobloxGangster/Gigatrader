from __future__ import annotations

# --- add repo root to sys.path so `import ui.*` always works ---
from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parents[1]  # repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import importlib
from typing import Dict, Any, List, Tuple, Callable, Optional

import streamlit as st
from ui.services.backend import BrokerAPI, get_backend
from ui.state import AppSessionState, init_session_state

# ---- Page registry (label, slug, module) ----
NAV_ITEMS: List[Tuple[str, str, str]] = [
    ("Control Center",     "control-center", "ui.pages.control_center"),
    ("Option Chain",       "option-chain",   "ui.pages.option_chain"),
    ("Diagnostics / Logs", "diagnostics",    "ui.pages.diagnostics_logs"),
]

_LABELS = [p[0] for p in NAV_ITEMS]
_SLUGS  = [p[1] for p in NAV_ITEMS]

api: BrokerAPI | None = None
state: AppSessionState | None = None

# Map slugs to module names (only include pages that exist in repo)
PAGES = {
    "control-center": "ui.pages.control_center",
    "diagnostics": "ui.pages.diagnostics_logs",
    "diagnostics-logs": "ui.pages.diagnostics_logs",
    "option-chain": "ui.pages.option_chain",
    "orders-positions": "ui.pages.orders_positions",
    "equity-risk": "ui.pages.equity_risk",
    "logs-pacing": "ui.pages.logs_pacing",
    # add others here as needed
}


def _call_render(mod, *args):
    """
    Call a page module's render function.
    Support either render(api, state) or render() for legacy pages.
    """
    fn: Optional[Callable] = getattr(mod, "render", None)
    if fn is None:
        raise RuntimeError(f"{mod.__name__} has no `render` function")
    try:
        return fn(api, state)  # preferred signature in this app
    except TypeError:
        return fn()  # fallback for older pages

def _qp_get() -> Dict[str, Any]:
    """Robust query param getter across Streamlit versions."""
    try:
        return dict(st.query_params)
    except Exception:
        # legacy fallback
        raw = st.experimental_get_query_params()
        return {k: (v[0] if isinstance(v, list) and v else v) for k, v in raw.items()}

def _qp_set(**kwargs) -> None:
    """Robust query param setter across Streamlit versions."""
    try:
        st.query_params.clear()
        st.query_params.update(kwargs)
    except Exception:
        st.experimental_set_query_params(**kwargs)

def _normalize_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    # Support legacy aliases
    if s in {"logs", "diagnostics-logs", "diagnostics_logs"}:
        s = "diagnostics"
    if s not in _SLUGS and s not in PAGES:
        s = "control-center"
    return s

def _render_nav(current_slug: str) -> str:
    """Render main-area selectbox (popover opens reliably for Playwright)."""
    st.markdown("#### Navigation")
    idx = _SLUGS.index(current_slug) if current_slug in _SLUGS else 0
    choice = st.selectbox(
        "Navigate",
        _LABELS,
        index=idx,
        key="global-nav-select",
        help="Switch pages",
    )
    dest_slug = _SLUGS[_LABELS.index(choice)]
    if dest_slug != current_slug:
        _qp_set(page=dest_slug)
        st.rerun()
    return current_slug

def main():
    global api, state
    try:
        st.set_page_config(page_title="Gigatrader", layout="wide")
    except Exception:
        pass
    raw_slug = (
        st.query_params.get("page", ["control-center"])[0]
        if hasattr(st, "query_params")
        else st.experimental_get_query_params().get("page", ["control-center"])[0]
    )
    slug = _normalize_slug(str(raw_slug))
    _render_nav(slug)  # Render nav FIRST so tests can click immediately

    state = init_session_state()
    api = get_backend()

    modname = PAGES.get(slug, "ui.pages.control_center")

    try:
        mod = importlib.import_module(modname)
    except Exception as e:  # noqa: BLE001
        st.exception(e)
    else:
        _call_render(mod)

if __name__ == "__main__":
    main()
