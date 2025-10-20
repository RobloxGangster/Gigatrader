from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List

import streamlit as st

from ui.services.backend import BrokerAPI
from ui.state import AppSessionState, RiskSnapshot
from ui.utils.compat import rerun as st_rerun
from ui.utils.format import fmt_currency, fmt_num, fmt_pct
from ui.utils.num import to_float

from ui.pages import backtest_reports, control_center, logs_pacing, option_chain

RESULTS_KEY = "ui_diagnostics_results"
REPORT_KEY = "ui_diagnostics_report"

PAGES: List[tuple[str, Any]] = [
    ("Control Center", control_center),
    ("Option Chain", option_chain),
    ("Backtest Reports", backtest_reports),
    ("Logs", logs_pacing),
]


@dataclass
class PageResult:
    name: str
    ok: bool
    error: str | None
    traceback: str | None
    notes: list[str]


def _lint_snapshot(snap: RiskSnapshot | None) -> list[str]:
    notes: list[str] = []
    if snap is None:
        notes.append("RiskSnapshot: missing/None")
        return notes
    leverage = to_float(snap.leverage)
    if leverage and leverage < 0:
        notes.append("Leverage is negative (unexpected).")
    loss_pct = to_float(snap.daily_loss_pct)
    if loss_pct and loss_pct < 0:
        notes.append("Daily loss % negative (ok if gains; ensure sign convention).")
    notes.append(
        "Snapshot: "
        f"equity {fmt_currency(snap.equity)}, "
        f"cash {fmt_currency(snap.cash)}, "
        f"day P&L {fmt_num(snap.day_pnl)}, "
        f"exposure {fmt_pct(snap.exposure_pct)}"
    )
    return notes


def _store_results(results: list[PageResult], report: dict[str, Any]) -> None:
    st.session_state[RESULTS_KEY] = [asdict(r) for r in results]
    st.session_state[REPORT_KEY] = report


def _load_results() -> tuple[list[PageResult], dict[str, Any] | None]:
    stored = st.session_state.get(RESULTS_KEY) or []
    report = st.session_state.get(REPORT_KEY)
    result_objs = [PageResult(**data) for data in stored]
    return result_objs, report


def _clear_results() -> None:
    st.session_state.pop(RESULTS_KEY, None)
    st.session_state.pop(REPORT_KEY, None)
    st_rerun()


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Diagnostics / Logs")
    st.subheader("Logs & Pacing")
    st.write("Runs each page, captures exceptions, and writes a JSON report under `logs/`.")

    run_all = st.button("Run full sweep", type="primary")
    results: list[PageResult] = []
    report: dict[str, Any] | None = None

    if run_all:
        for name, module in PAGES:
            with st.expander(f"Page: {name}", expanded=False):
                ok = True
                err = None
                tb = None
                notes: list[str] = []
                try:
                    if name == "Control Center":
                        try:
                            snap = api.get_risk_snapshot()
                            notes.extend(_lint_snapshot(snap))
                        except Exception as exc:  # noqa: BLE001
                            notes.append(f"Error fetching /risk: {exc}")

                    module.render(api, state)
                    st.success("Rendered without exception.")
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    err = str(exc)
                    tb = traceback.format_exc()
                    st.exception(exc)
                results.append(
                    PageResult(name=name, ok=ok, error=err, traceback=tb, notes=notes)
                )

        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "results": [asdict(r) for r in results],
        }
        Path("logs").mkdir(exist_ok=True)
        out = Path("logs") / f"ui_diagnostics_{int(time.time())}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        st.success(f"Report saved: {out}")
        st.download_button(
            "Download report",
            data=json.dumps(report, indent=2),
            file_name=out.name,
            mime="application/json",
            key="diagnostics_download",
        )
        _store_results(results, report)

    if not run_all:
        results, report = _load_results()
        for result in results:
            with st.expander(f"Page: {result.name}", expanded=not result.ok):
                if result.ok:
                    st.success("Rendered without exception.")
                else:
                    st.error(result.error or "Unknown error")
                    if result.traceback:
                        st.code(result.traceback)
                if result.notes:
                    st.write("Notes:")
                    for note in result.notes:
                        st.markdown(f"- {note}")

    if report:
        st.download_button(
            "Download last report",
            data=json.dumps(report, indent=2),
            file_name="ui_diagnostics_latest.json",
            mime="application/json",
            key="diagnostics_download_latest",
        )
        if st.button("Clear results"):
            _clear_results()
