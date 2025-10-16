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
from ui.utils.diagnostics import UI_DIAG_PATH, run_ui_diagnostics


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
    st.title("Diagnostics / Logs")
    st.header("Diagnostics / Logs")
    st.caption("Logs & Pacing")
    st.caption("DIAGNOSTICS_READY")
    level = st.selectbox("Level", ["", "INFO", "WARN", "ERROR"], index=0)
    component = st.text_input("Component contains", value="")
    correlation = st.text_input("Correlation id", value="")

    st.subheader("UI Diagnostics")
    with st.form("ui_diag_form", clear_on_submit=False):
        run_now = st.form_submit_button("Run UI Diagnostics")
    if run_now:
        result = run_ui_diagnostics(api)
        st.success(
            f"Ran {result['summary']['total']} checks — "
            f"{result['summary']['passed']} passed, {result['summary']['failed']} failed."
        )
        with st.expander("Details", expanded=True):
            st.json(result)

    st.subheader("Broker Sanity")
    try:
        acc = api.get_account()
        pv = acc.get("portfolio_value") or acc.get("equity")
        st.write(
            "Portfolio Value: **{pv}**  |  Cash: **{cash}**  |  BP: **{bp}**".format(
                pv=pv,
                cash=acc.get("cash"),
                bp=acc.get("buying_power"),
            )
        )
    except Exception as exc:  # noqa: BLE001 - best effort surface
        st.warning(f"Account check failed: {exc}")

    # Show last few saved diagnostic runs
    st.markdown("**Recent Diagnostic Runs**")
    if UI_DIAG_PATH.exists():
        last = UI_DIAG_PATH.read_text(encoding="utf-8").strip().splitlines()[-10:]
        rows = [json.loads(x) for x in last if x.strip()]
        for r in rows[::-1]:
            s = r.get("summary", {})
            st.write(
                f"• {s.get('timestamp','?')} — {s.get('passed',0)}/{s.get('total',0)} passed "
                f"(profile={s.get('profile','?')})"
            )
            with st.expander("View", expanded=False):
                st.json(r)
    else:
        st.info("No diagnostic runs recorded yet.")

    log_events = [event.model_dump() for event in api.get_logs(200, level or None)]
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
    pacing_chart = pacing_history_chart(pacing.history, pacing.max_rpm)
    if pacing_chart is not None:
        st.plotly_chart(pacing_chart, use_container_width=True)
    else:
        st.warning("Plotly not installed, showing basic pacing line chart.")
        history_df = pd.DataFrame({"rpm": [float(v) for v in pacing.history]})
        st.line_chart(history_df["rpm"])
    st.caption(
        f"RPM {pacing.rpm} · backoff events {pacing.backoff_events} · retries {pacing.retries}"
    )

    if st.button("Create Repro Bundle"):
        orders = [order.model_dump() for order in api.get_orders()]
        trades = [trade.model_dump() for trade in api.get_trades(None)]
        bundle = _create_repro_bundle(state, log_events, orders, trades)
        st.success(f"Bundle created: {bundle}")
