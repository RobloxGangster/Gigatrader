from __future__ import annotations

"""Machine learning operations page."""


from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.services.backend import BrokerAPI
from ui.services.config import mock_mode
from ui.state import AppSessionState
from ui.utils.num import to_float

DEFAULT_SYMBOL = "AAPL"


def _render_metrics(metrics: Dict[str, Any]) -> None:
    if not metrics:
        st.info("No metrics available for the current model.")
        return
    df = pd.DataFrame(metrics.items(), columns=["Metric", "Value"])
    df["Value"] = df["Value"].apply(to_float)
    st.table(df)


def _render_importances(importances: List[Dict[str, Any]]) -> None:
    if not importances:
        st.info("Feature importances are not available.")
        return
    df = pd.DataFrame(importances)
    df = df.sort_values("importance", ascending=False).head(15)
    st.bar_chart(df.set_index("feature"))


def render(api: BrokerAPI, state: AppSessionState) -> None:  # noqa: ARG001
    st.title("ML Ops")
    st.caption("Inspect model health, probe features, and trigger lightweight training runs.")

    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    try:
        status = api.get_ml_status()
    except Exception as exc:  # pragma: no cover - UI safeguard
        st.error(f"Unable to reach ML endpoint: {exc}")
        return

    if status.get("status") == "missing" or not status.get("model"):
        st.warning("No trained model is registered yet.")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Model", status.get("model"))
        if status.get("created_at"):
            col2.metric("Created", status.get("created_at"))
        st.subheader("Validation Metrics")
        _render_metrics(status.get("metrics", {}))
        st.subheader("Top Features")
        _render_importances(status.get("feature_importances", []))

    with st.expander("Feature Snapshot"):
        symbol = st.text_input("Symbol", value=DEFAULT_SYMBOL)
        if st.button("Fetch Features", key="fetch_features"):
            try:
                features = api.get_ml_features(symbol)
            except Exception as exc:  # pragma: no cover
                st.error(f"Failed to fetch features: {exc}")
            else:
                st.json(features)
        if st.button("Predict", key="predict_symbol"):
            try:
                response = api.ml_predict(symbol)
            except Exception as exc:  # pragma: no cover
                st.error(f"Prediction failed: {exc}")
            else:
                if response.get("error"):
                    st.warning(response["error"])
                else:
                    prob = to_float(response.get("p_up_15m"))
                    st.success(f"Probability of upside in 15m: {prob:.3f}")

    if mock_mode():
        if st.button("Train (Mock)"):
            try:
                result = api.ml_train([DEFAULT_SYMBOL, "MSFT"])
            except Exception as exc:  # pragma: no cover
                st.error(f"Training failed: {exc}")
            else:
                if result.get("error"):
                    st.warning(result["error"])
                else:
                    st.success("Training completed.")
                    st.json(result)
