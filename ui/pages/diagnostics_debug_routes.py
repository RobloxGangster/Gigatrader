from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st


def _resolve_base(session_state: Any, app_state: Any) -> str:
    """Determine the backend base URL from session state fallbacks."""

    default_base = "http://127.0.0.1:8000"
    candidates: List[str] = []

    if hasattr(session_state, "get"):
        candidates.append(session_state.get("backend_base"))
        candidates.append(session_state.get("api.base_url"))
        api_obj = session_state.get("api") if hasattr(session_state, "get") else None
        if api_obj is not None:
            base_attr = getattr(api_obj, "base", None)
            if callable(base_attr):
                try:
                    candidates.append(base_attr())
                except Exception:  # pragma: no cover - defensive best effort
                    pass
            candidates.append(getattr(api_obj, "base_url", None))
    if app_state is not None:
        for attr in ("backend_base", "api_base", "api_base_url"):
            candidates.append(getattr(app_state, attr, None))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.rstrip("/")

    return default_base


def render(_, session_state, state=None) -> None:
    """Render diagnostics for backend routes by querying /debug/routes."""

    st.header("Diagnostics / Debug Routes")

    base = _resolve_base(session_state, state)
    url = f"{base}/debug/routes"

    try:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        payload: Dict[str, Dict[str, Any]] = response.json()
    except Exception as exc:  # noqa: BLE001 - display failure in UI
        st.error(f"Failed to load {url}: {exc}")
        return

    rows: List[Dict[str, Any]] = []
    for route, info in payload.items():
        if not isinstance(info, dict):
            info = {"ok": False, "status": None, "elapsed_ms": None, "error": "invalid payload"}
        rows.append(
            {
                "route": route,
                "ok": info.get("ok"),
                "status": info.get("status"),
                "elapsed_ms": info.get("elapsed_ms"),
                "error": info.get("error"),
            }
        )

    if not rows:
        st.info("No routes returned from backend diagnostics endpoint.")
        return

    df = pd.DataFrame(rows)
    df = df.sort_values(["ok", "route"], ascending=[False, True])
    st.dataframe(df, hide_index=True, use_container_width=True)

    failing = [row for row in rows if not row.get("ok")]
    if failing:
        st.error("One or more endpoints are failing. See table above.")
    else:
        st.success("All endpoints OK.")
