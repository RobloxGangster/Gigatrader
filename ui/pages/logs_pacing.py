"""Logs & Pacing page."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable
import zipfile

import pandas as pd
import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState
from ui.utils.charts import pacing_history_chart


def _to_ndjson(records: Iterable[dict]) -> str:
    return "\n".join(json.dumps(record, default=str) for record in records)


def _create_repro_bundle(
    state: AppSessionState,
    logs: list[dict[str, str]],
    orders: list[dict[str, str]],
    trades: list[dict[str, str]],
) -> Path:
    repro_dir = Path("repros")
    repro_dir.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    bundle_path = repro_dir / f"repro_{timestamp}.zip"
    with zipfile.ZipFile(bundle_path, "w") as bundle:
        config_path = Path("config.example.yaml")
        presets_path = Path("RISK_PRESETS.md")
        if config_path.exists():
            bundle.write(config_path, arcname="config.yaml")
        if presets_path.exists():
            bundle.write(presets_path, arcname="RISK_PRESETS.md")
        bundle.writestr("logs.ndjson", _to_ndjson(logs[-200:]))
        bundle.writestr("orders.ndjson", _to_ndjson(orders[-200:]))
        bundle.writestr("trades.ndjson", _to_ndjson(trades[-200:]))
        bundle.writestr(
            "strategy_params.json",
            json.dumps(state.strategy_params or {}, indent=2),
        )
        bundle.writestr(
            "session.json",
            json.dumps(
                {
                    "profile": state.profile,
                    "symbol": state.selected_symbol,
                    "run_id": state.run_id,
                    "trace_id": state.last_trace_id,
                },
                indent=2,
            ),
        )
    return bundle_path


def _logs_table(logs: list[dict]) -> None:
    df = pd.DataFrame(logs)
    st.dataframe(df, use_container_width=True)
    st.download_button(
        "Download logs (NDJSON)",
        _to_ndjson(logs).encode("utf-8"),
        file_name="logs.ndjson",
        mime="application/x-ndjson",
    )


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Logs & Pacing")
    level = st.selectbox("Level", ["", "INFO", "WARN", "ERROR"], index=0)
    component = st.text_input("Component contains", value="")
    correlation = st.text_input("Correlation id", value="")

    log_events = [event.dict() for event in api.get_logs(200, level or None)]
    if component:
        log_events = [log for log in log_events if component.lower() in log["component"].lower()]
    if correlation:
        log_events = [
            log
            for log in log_events
            if correlation.lower() in (log.get("correlation_id") or "").lower()
        ]

    _logs_table(log_events)

    pacing = api.get_pacing_stats()
    st.plotly_chart(pacing_history_chart(pacing.history, pacing.max_rpm), use_container_width=True)
    st.caption(
        f"RPM {pacing.rpm} · backoff events {pacing.backoff_events} · retries {pacing.retries}"
    )

    if st.button("Create Repro Bundle"):
        orders = [order.dict() for order in api.get_orders()]
        trades = [trade.dict() for trade in api.get_trades(None)]
        bundle = _create_repro_bundle(state, log_events, orders, trades)
        st.success(f"Bundle created: {bundle}")
