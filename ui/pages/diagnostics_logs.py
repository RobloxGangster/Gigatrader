from __future__ import annotations

from typing import Any, Dict

from typing import Any, Dict

import requests
import streamlit as st

from ui.services.config import api_base_url
from ui.utils.st_compat import safe_rerun

_MESSAGE_KEY = "diagnostics_logs_status"
_REFRESH_TOGGLE = "_refresh_logs_toggle"


def _base_url() -> str:
    return api_base_url()


def _post(path: str) -> Dict[str, Any]:
    url = f"{_base_url()}/{path.lstrip('/')}"
    response = requests.post(url, timeout=10)
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("application/json"):
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    return {}


def _get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{_base_url()}/{path.lstrip('/')}"
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("application/json"):
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    return {}


def render(*_: Any) -> None:
    st.header("Diagnostics / Logs")

    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        if st.button("Run Diagnostics", use_container_width=True):
            try:
                resp = _post("/diagnostics/run")
                message = str(resp.get("message") or "Diagnostics complete")
                st.session_state[_MESSAGE_KEY] = {"ok": True, "message": message}
            except Exception as exc:  # noqa: BLE001 - surface to UI
                st.session_state[_MESSAGE_KEY] = {
                    "ok": False,
                    "message": f"Diagnostics failed: {exc}",
                }
            safe_rerun()
    with col2:
        if st.button("Refresh Logs", use_container_width=True):
            st.session_state[_REFRESH_TOGGLE] = not st.session_state.get(_REFRESH_TOGGLE, False)
            safe_rerun()

    status = st.session_state.get(_MESSAGE_KEY)
    if isinstance(status, dict) and status.get("message"):
        if status.get("ok"):
            st.success(status["message"])
        else:
            st.error(status["message"])

    st.caption("Recent application log tail")
    try:
        data = _get("/logs/tail", params={"lines": 200})
        lines = data.get("lines", []) if isinstance(data, dict) else []
        if lines:
            st.code("\n".join(str(line) for line in lines))
        else:
            st.info("No log lines available yet.")
    except Exception as exc:  # noqa: BLE001 - show warning to user
        st.warning(f"Unable to fetch logs: {exc}")
