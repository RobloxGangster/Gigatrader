from __future__ import annotations
import os
import requests
import streamlit as st
from urllib.parse import urljoin

DEFAULT_API = "http://127.0.0.1:8000"

def _base_url() -> str:
    # Prefer a value the Control Center or Home set; fall back to env or default
    return (
        st.session_state.get("api.base_url")
        or os.getenv("API_BASE_URL")
        or DEFAULT_API
    )

def build_url(path: str) -> str:
    return urljoin(_base_url().rstrip("/") + "/", path.lstrip("/"))

def get_json(path: str, params: dict | None = None, timeout: float = 8.0):
    url = build_url(path)
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    # Backend may return text lines for logs; try json first but allow text fallback in caller.
    try:
        return r.json()
    except Exception:
        return r.text

def get_text(path: str, params: dict | None = None, timeout: float = 8.0) -> str:
    url = build_url(path)
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text
