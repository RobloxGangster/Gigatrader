from __future__ import annotations

"""Navigation metadata and helpers for the Streamlit UI."""

import inspect
from importlib import import_module
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import streamlit as st

from ui.state import AppSessionState, init_session_state
from ui.services.backend import BrokerAPI, get_backend

# Registry of first-class navigation items shown in the global selectbox.
# Each item includes the human-facing label, canonical slug (used in the
# query string), and the import path for the associated Streamlit page module.
NAV_ITEMS: List[Dict[str, str]] = [
    {
        "label": "Control Center",
        "slug": "control-center",
        "import_path": "ui.pages.control_center",
        "render_name": "render",
    },
    {
        "label": "Diagnostics / Logs",
        "slug": "diagnostics",
        "import_path": "ui.pages.diagnostics_logs",
        "render_name": "render",
    },
    {
        "label": "Diagnostics / Debug Routes",
        "slug": "diagnostics-debug-routes",
        "import_path": "ui.pages.diagnostics_debug_routes",
        "render_name": "render",
    },
    {
        "label": "Option Chain",
        "slug": "option-chain",
        "import_path": "ui.pages.option_chain",
        "render_name": "render",
    },
    {
        "label": "Orders & Positions",
        "slug": "orders-positions",
        "import_path": "ui.pages.orders_positions",
        "render_name": "render",
    },
    {
        "label": "Trade Blotter",
        "slug": "trade-blotter",
        "import_path": "ui.pages.trade_blotter",
        "render_name": "render",
    },
    {
        "label": "Strategy Backtests",
        "slug": "strategy-backtests",
        "import_path": "ui.pages.backtest",
        "render_name": "render",
    },
    {
        "label": "Backtest Reports",
        "slug": "backtest-reports",
        "import_path": "ui.pages.backtest_reports",
        "render_name": "render",
    },
    {
        "label": "Strategy Tuning",
        "slug": "strategy-tuning",
        "import_path": "ui.pages.strategy_tuning",
        "render_name": "render",
    },
    {
        "label": "Signal Preview",
        "slug": "signal-preview",
        "import_path": "ui.pages.signals",
        "render_name": "render",
    },
    {
        "label": "Research",
        "slug": "research",
        "import_path": "ui.pages.research",
        "render_name": "render",
    },
    {
        "label": "Data Inspector",
        "slug": "data-inspector",
        "import_path": "ui.pages.data_inspector",
        "render_name": "render",
    },
    {
        "label": "ML Ops",
        "slug": "ml-ops",
        "import_path": "ui.pages.ml",
        "render_name": "render",
    },
    {
        "label": "Equity & Risk",
        "slug": "equity-risk",
        "import_path": "ui.pages.equity_risk",
        "render_name": "render",
    },
]


# Legacy slugs that should continue to resolve for deep links.
_SLUG_ALIASES = {
    "diagnostics-logs": "diagnostics",
    "diagnostics_logs": "diagnostics",
    "logs": "diagnostics",
    "log": "diagnostics",
}


def slugify(label: str) -> str:
    """Convert a page label into a canonical slug."""

    cleaned = label.lower().replace(" / ", "-").replace("/", "-").replace(" ", "-")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch == "-")


def _iter_candidates() -> Iterable[Dict[str, str]]:
    yield from NAV_ITEMS


def find_by_slug(slug: str | None) -> Optional[Dict[str, str]]:
    """Locate a navigation item by slug or known alias."""

    if not slug:
        return None
    target = slug.strip().lower()
    target = _SLUG_ALIASES.get(target, target)
    for item in _iter_candidates():
        if target == item["slug"] or target == slugify(item["label"]):
            return item
    return None


def default_slug() -> str:
    return "control-center"


def resolve_renderer(item: Dict[str, str]) -> Callable[..., Any]:
    module = import_module(item["import_path"])
    return getattr(module, item["render_name"])


class _DependencyResolutionError(RuntimeError):
    """Kept for backward compatibility; no longer raised for missing optional deps."""


def _resolve_state() -> Tuple[Any, AppSessionState]:
    """Return the raw Streamlit session state and the typed app state."""

    session_state = st.session_state
    app_state = session_state.get("app_state") if hasattr(session_state, "get") else None
    if not isinstance(app_state, AppSessionState):
        app_state = init_session_state()
    return session_state, app_state


def _resolve_api(session_state: Any) -> Optional[BrokerAPI]:
    """Prefer cached API handle from state before creating a new backend client."""

    api_candidate: Optional[BrokerAPI] = None
    if hasattr(session_state, "get"):
        api_candidate = session_state.get("api") or session_state.get("backend")
    if api_candidate is not None:
        return api_candidate
    try:
        api_candidate = get_backend()
    except Exception:  # pragma: no cover - backend discovery may fail in UI tests
        api_candidate = None
    else:
        if hasattr(session_state, "__setitem__"):
            try:
                session_state["api"] = api_candidate
            except Exception:  # pragma: no cover - session state may be frozen
                pass
    return api_candidate


def _build_injected_args(
    fn: Callable[..., Any],
    session_state: Any,
    app_state: AppSessionState,
    api: Optional[BrokerAPI],
) -> Tuple[List[Any], Dict[str, Any]]:
    """Return args/kwargs for ``fn`` while treating unknown params as optional."""

    signature = inspect.signature(fn)
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}

    for name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        injected: Any = None
        has_injected = False

        if name in {"_", "st", "streamlit"}:
            injected = st
            has_injected = True
        elif name in {"state", "app_state"} or param.annotation is AppSessionState:
            injected = app_state
            has_injected = True
        elif name in {"session_state", "session"}:
            injected = session_state
            has_injected = True
        elif name in {"api", "backend", "client", "svc", "broker", "broker_api"} or (
            param.annotation is BrokerAPI
        ):
            injected = api
            has_injected = True

        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            if has_injected:
                args.append(injected)
            elif param.default is inspect._empty:
                args.append(None)
        elif param.kind is inspect.Parameter.KEYWORD_ONLY:
            if has_injected:
                kwargs[name] = injected
            elif param.default is inspect._empty:
                kwargs[name] = None

    return args, kwargs


def dispatch_render(fn: Callable[..., Any]) -> Any:
    """Invoke a page render function with adaptive dependency injection."""

    session_state, app_state = _resolve_state()
    api = _resolve_api(session_state)
    args, kwargs = _build_injected_args(fn, session_state, app_state, api)
    return fn(*args, **kwargs)


__all__ = [
    "NAV_ITEMS",
    "slugify",
    "find_by_slug",
    "default_slug",
    "resolve_renderer",
    "dispatch_render",
]
