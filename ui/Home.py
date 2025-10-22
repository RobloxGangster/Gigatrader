from __future__ import annotations
import pathlib
import runpy
import streamlit as st
from typing import Dict, Any, List, Tuple

# ---- Page registry (label, slug, file) ----
PAGES: List[Tuple[str, str, str]] = [
    ("Control Center",     "control-center", "ui/pages/control_center.py"),
    ("Option Chain",       "option-chain",   "ui/pages/option_chain.py"),
    ("Diagnostics / Logs", "diagnostics",    "ui/pages/diagnostics.py"),
]

_LABELS = [p[0] for p in PAGES]
_SLUGS  = [p[1] for p in PAGES]
_FILES  = {p[1]: p[2] for p in PAGES}

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
    if s not in _SLUGS:
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
    try:
        st.set_page_config(page_title="Gigatrader", layout="wide")
    except Exception:
        pass
    qp = _qp_get()
    slug = _normalize_slug(str(qp.get("page") or ""))
    _render_nav(slug)  # Render nav FIRST so tests can click immediately

    target = pathlib.Path(_FILES[slug]).resolve()
    # Run the selected page as a standalone script (so it can render its own header)
    runpy.run_path(str(target), run_name="__main__")

if __name__ == "__main__":
    main()
