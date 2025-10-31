from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import streamlit as st


@dataclass
class PageSpec:
    slug: str
    title: str
    module: str


def _default_pages() -> List[PageSpec]:
    # Order & labels aligned to requested menu. Modules that don't exist are skipped downstream.
    return [
        PageSpec("control_center", "Control Center", "ui.pages.control_center"),
        PageSpec("signals", "Signals", "ui.pages.signals"),  # fallback handled below
        PageSpec("strategy_backtests", "Strategy Backtests", "ui.pages.strategy_backtests"),
        PageSpec("backtest_reports", "Backtest Reports", "ui.pages.backtest_reports"),
        PageSpec("ml_ops", "ML Ops", "ui.panels.ml_predict"),  # ML landing = predict panel
        PageSpec("option_chain", "Option Chain", "ui.pages.option_chain"),
        PageSpec("diagnostics", "Diagnostics / Logs", "ui.pages.diagnostics_logs"),
        PageSpec("stream_status", "Stream Status", "ui.pages.stream_status"),  # optional
        PageSpec("metrics_extended", "Metrics (Extended)", "ui.panels.metrics_extended"),  # optional
        PageSpec("ml_calibration", "ML Calibration", "ui.panels.ml_calibration"),  # optional
    ]


def _safe_import(module_path: str):
    try:
        return importlib.import_module(module_path)
    except Exception:
        return None


def _import_render(module_path: str) -> Callable:
    mod = _safe_import(module_path)
    if mod and hasattr(mod, "render"):
        return getattr(mod, "render")
    if mod and hasattr(mod, "main"):
        fn = getattr(mod, "main")
        return lambda api, state: fn()
    # Special fallback for Signals: try alternate preview module
    if module_path == "ui.pages.signals":
        alt = _safe_import("ui.pages.signals_preview")
        if alt and hasattr(alt, "render"):
            return getattr(alt, "render")
    raise ImportError(f"{module_path} must define render(api, state) or main()")


def build_page_map(pages: Optional[Iterable[PageSpec]] = None) -> Dict[str, Tuple[str, Callable]]:
    specs = list(pages) if pages is not None else _default_pages()
    page_map: Dict[str, Tuple[str, Callable]] = {}
    for spec in specs:
        try:
            renderer = _import_render(spec.module)
        except ImportError:
            continue
        page_map[spec.slug] = (spec.title, renderer)
    return page_map


def render_sidebar(page_map: Dict[str, Tuple[str, Callable]], key: str = "nav_current") -> str:
    if not page_map:
        raise ValueError("page_map cannot be empty")
    slugs = list(page_map.keys())
    titles = [entry[0] for entry in page_map.values()]
    slug_by_title = {title: slug for slug, title in zip(slugs, titles)}
    if key not in st.session_state or st.session_state[key] not in page_map:
        st.session_state[key] = slugs[0]
    current_title = page_map[st.session_state[key]][0]
    select_key = f"{key}_select"
    selected_title = st.sidebar.selectbox(
        "Navigation",
        titles,
        index=titles.index(current_title),
        key=select_key,
    )
    selected_slug = slug_by_title[selected_title]
    if st.session_state[key] != selected_slug:
        st.session_state[key] = selected_slug
    return st.session_state[key]


def render_quickbar(page_map: Dict[str, Tuple[str, Callable]], key: str = "nav_current") -> None:
    if not page_map:
        return
    preferred_order = [
        "control_center",
        "signals",
        "strategy_backtests",
        "backtest_reports",
        "option_chain",
        "diagnostics",
    ]
    quick = [k for k in preferred_order if k in page_map]
    if not quick:
        return
    st.write("")  # spacing
    cols = st.columns(min(len(quick), 6))
    for col, k in zip(cols, quick):
        with col:
            title = page_map[k][0]
            if st.button(title, width="stretch", key=f"quick_{k}"):
                if st.session_state.get(key) != k:
                    st.session_state[key] = k
                    st.rerun()
