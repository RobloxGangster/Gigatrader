from __future__ import annotations

import json
from typing import Any

import streamlit as st

from ui.lib.api_client import ApiClient


def _resolve_client(
    maybe_client: Any,
    *,
    api_base: str | None = None,
    api_client: ApiClient | None = None,
) -> ApiClient:
    if isinstance(maybe_client, ApiClient):
        return maybe_client
    bases = [api_base] if api_base else None
    return api_client or ApiClient(bases=bases)


def render(
    api: Any | None = None,
    *_: Any,
    api_base: str | None = None,
    api_client: ApiClient | None = None,
) -> None:
    st.header("ML Predict (Registry-backed)")
    st.caption(
        "Calls /ml/predict using models registered in artifacts/. Use for quick what-if scoring."
    )

    client = _resolve_client(api, api_base=api_base, api_client=api_client)
    st.caption(f"Resolved API: {client.base()}")

    model_name = st.text_input("Model name", value="toy_api")
    alias = st.text_input("Alias (or leave 'production')", value="production")

    st.subheader("Features")
    st.write(
        "Enter JSON list of items: [{'symbol':'AAPL','features':{'a':0.1,'b':0.2,'c':0.3,'d':0.4}}, ...]"
    )
    default_items = [
        {"symbol": "AAPL", "features": {"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.4}},
        {"symbol": "MSFT", "features": {"a": 0.5, "b": 0.1, "c": -0.3, "d": 0.9}},
    ]
    items_json = st.text_area("Items JSON", value=json.dumps(default_items, indent=2), height=200)

    if st.button("Predict"):
        try:
            items = json.loads(items_json)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
            return

        payload = {"model_name": model_name, "alias": alias, "items": items}
        try:
            with st.spinner("Calling /ml/predict..."):
                response = client.request("POST", "/ml/predict", json=payload)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            st.exception(exc)
            return

        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
        else:
            try:
                data = json.loads(response.text or "{}")
            except Exception:
                data = {"raw": response.text}

        st.success("Prediction complete")
        st.json(data)
