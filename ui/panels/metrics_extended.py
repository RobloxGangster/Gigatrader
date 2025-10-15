"""Streamlit panel for extended telemetry metrics."""

from __future__ import annotations

from typing import Any, Dict

import requests
import streamlit as st


def _format_float(value: Any, *, precision: int = 2) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):.{precision}f}"
    except Exception:
        return str(value)


def render(api_base: str = "http://127.0.0.1:8000") -> None:
    st.header("Extended Trading Metrics")
    st.caption("Snapshots /metrics/extended for latency, rejects, and data health.")

    st.button("Refresh metrics", type="primary", on_click=st.experimental_rerun)

    try:
        response = requests.get(f"{api_base}/metrics/extended", timeout=5)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - UI guard
        st.error(f"Failed to load metrics: {exc}")
        return
    data: Dict[str, Any] = response.json()

    latency = data.get("order_latency_ms", {})
    rejects = data.get("order_rejects_total", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("Order latency p50 (ms)", _format_float(latency.get("p50"), precision=1))
    col2.metric("Order latency p95 (ms)", _format_float(latency.get("p95"), precision=1))
    col3.metric("Samples", f"{int(latency.get('count', 0))}")

    st.metric("Latest order latency (ms)", _format_float(latency.get("latest"), precision=1))

    st.subheader("Order rejects")
    st.write(f"Total rejects: {int(rejects.get('total', 0))}")
    by_code = rejects.get("by_code", {})
    if by_code:
        rows = [
            {"code": code, "count": count}
            for code, count in sorted(by_code.items(), key=lambda item: (-int(item[1]), item[0]))
        ]
        st.table(rows)
    else:
        st.info("No rejects recorded.")

    col_ws, col_data = st.columns(2)
    col_ws.metric("WS reconnects", int(data.get("ws_reconnects_total", 0)))
    col_data.metric(
        "Data staleness (sec)",
        _format_float(data.get("data_staleness_sec"), precision=2),
    )
