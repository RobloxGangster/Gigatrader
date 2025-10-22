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

import os
from typing import Any, Callable, Optional

import streamlit as st

from ui.pages import control_center, diagnostics_logs, option_chain
from ui.services.backend import BrokerAPI, get_backend
from ui.state import AppSessionState, init_session_state

PAGE_REGISTRY: dict[str, Callable[..., Any]] = {
    "control-center": control_center.render,
    "diagnostics": diagnostics_logs.render,
    "option-chain": option_chain.render,
}

PAGE_LABELS: dict[str, str] = {
    "control-center": "Control Center",
    "diagnostics": "Diagnostics / Logs",
    "option-chain": "Option Chain",
}

SLUG_ALIASES: dict[str, str] = {
    "diagnostics-logs": "diagnostics",
    "diagnostics_logs": "diagnostics",
    "logs": "diagnostics",
    "log": "diagnostics",
}


def _init_session_defaults() -> None:
    st.session_state.setdefault("nav.slug", "control-center")
    st.session_state.setdefault("telemetry.autorefresh", False)
    st.session_state.setdefault(
        "api.base_url", os.getenv("API_BASE_URL") or "http://127.0.0.1:8000"
    )


def _resolve_slug(raw: str | None) -> str:
    slug = (raw or "").strip().lower()
    slug = SLUG_ALIASES.get(slug, slug)
    if slug not in PAGE_REGISTRY:
        slug = "control-center"
    return slug


def _slug_from_query() -> str:
    try:
        query = st.query_params
        raw_value = query.get("page")
    except Exception:  # pragma: no cover - Streamlit < 1.30 fallback
        query = st.experimental_get_query_params()
        raw_value = query.get("page")

    if isinstance(raw_value, list):
        value = raw_value[0] if raw_value else None
    else:
        value = raw_value

    if not value:
        value = str(st.session_state.get("nav.slug", ""))

    return _resolve_slug(value)


def _select_page(current: str) -> str:
    st.markdown("### Navigation ↪")
    labels = [PAGE_LABELS[slug] for slug in PAGE_REGISTRY]
    slugs = list(PAGE_REGISTRY)
    current_slug = current if current in PAGE_REGISTRY else "control-center"
    current_index = slugs.index(current_slug)

    label = st.selectbox(
        "Navigate",
        labels,
        index=current_index,
        key="nav.select",
        help="Jump between Gigatrader pages.",
    )
    chosen = slugs[labels.index(label)]

    if chosen != current_slug:
        st.session_state["nav.slug"] = chosen
        try:
            st.query_params["page"] = chosen
        except Exception:  # pragma: no cover - legacy fallback
            st.experimental_set_query_params(page=chosen)
        st.rerun()

    return chosen


def _call_render(fn: Callable[..., Any]) -> Optional[Any]:
    state: AppSessionState = init_session_state()
    api: BrokerAPI = get_backend()

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


def main() -> None:
    st.set_page_config(page_title="Gigatrader", layout="wide")
    _init_session_defaults()

    slug = _slug_from_query()
    st.session_state["nav.slug"] = slug
    slug = _select_page(slug)
    renderer = PAGE_REGISTRY.get(slug, control_center.render)
    _call_render(renderer)


if __name__ == "__main__":
    main()
