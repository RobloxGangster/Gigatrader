from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from ui.services.backend import BrokerAPI, get_backend
from ui.state import AppSessionState, init_session_state

# Ensure project root (parent of 'ui') is on sys.path so 'ui.*' imports work
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="Gigatrader", layout="wide")

# --- Page registry: slug -> ("Label", module_path, render_fn)
PAGES: dict[str, tuple[str, str, str]] = {
    "control-center": ("Control Center", "ui.pages.control_center", "render"),
    "diagnostics": ("Diagnostics / Logs", "ui.pages.diagnostics_logs", "render"),
    "option-chain": ("Option Chain", "ui.pages.option_chain", "render"),
}

# Legacy aliases that should resolve to canonical slugs
SLUG_ALIASES: dict[str, str] = {
    "diagnostics-logs": "diagnostics",
    "diagnostics_logs": "diagnostics",
    "logs": "diagnostics",
    "log": "diagnostics",
}

# Session defaults
st.session_state.setdefault("nav.slug", "control-center")
st.session_state.setdefault("telemetry.autorefresh", False)


def _resolve_slug(raw: Any) -> str:
    slug = (str(raw or "").strip().lower())
    slug = SLUG_ALIASES.get(slug, slug)
    if slug not in PAGES:
        slug = "control-center"
    return slug


# Read & normalize query param
def _get_query_params() -> Dict[str, List[str]]:
    try:
        qp = st.query_params
        return {k: list(v) for k, v in qp.items()}
    except Exception:
        raw = st.experimental_get_query_params()
        return {k: (v if isinstance(v, list) else [v]) for k, v in raw.items()}


query_params = _get_query_params()
slug_candidates = query_params.get("page", [st.session_state["nav.slug"]])
slug = _resolve_slug(slug_candidates[0] if slug_candidates else "")
st.session_state["nav.slug"] = slug

# Top-of-page navigation
st.markdown("### Navigation ↪")
labels = [meta[0] for meta in PAGES.values()]
slugs = list(PAGES.keys())
current_index = slugs.index(slug)

new_label = st.selectbox(
    "Navigate",
    labels,
    index=current_index,
    key="nav.select",
    help="Jump between Gigatrader pages.",
)
new_slug = slugs[labels.index(new_label)]

# Update query params and rerun only if changed
if new_slug != slug:
    st.session_state["nav.slug"] = new_slug
    try:
        st.query_params.clear()
        st.query_params.update(page=new_slug)
    except Exception:
        st.experimental_set_query_params(page=new_slug)
    st.rerun()

# Resolve and call the page's render() as a package import (keeps ui.* imports working)
_, module_path, fn_name = PAGES[slug]
module = importlib.import_module(module_path)
render_fn: Callable[..., Any] = getattr(module, fn_name)


def _call_render(fn: Callable[..., Any]) -> Optional[Any]:
    state = init_session_state()
    api = get_backend()

    try:
        return fn(api, state)  # type: ignore[arg-type]
    except TypeError:
        try:
            return fn(api)  # type: ignore[arg-type]
        except TypeError:
            try:
                return fn(state)  # type: ignore[arg-type]
            except TypeError:
                return fn()


_call_render(render_fn)
