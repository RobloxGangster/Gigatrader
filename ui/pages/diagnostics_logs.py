from __future__ import annotations
import io
from datetime import datetime
from typing import Any, Iterable

import pandas as pd
import streamlit as st

from ui.lib.api_client import get_json, get_text, build_url

LIMIT_DEFAULT = 200


def render():
    st.header("Diagnostics / Logs")
    st.caption("Backend health, pacing, and recent logs. Exports available.")

    # Controls row
    c1, c2, c3, c4 = st.columns([1,1,1,2])
    with c1:
        run = st.button("Run Diagnostics", type="primary", help="Fetch /health, /pacing and recent logs.")
    with c2:
        st.toggle("Auto-refresh logs", key="diag.autorefresh", help="Refresh the log tail every few seconds.")
    with c3:
        limit = st.number_input("Lines", min_value=50, max_value=5000, value=LIMIT_DEFAULT, step=50)
    with c4:
        st.text_input("Filter (contains)", key="diag.filter", placeholder="error, worker, order id …")

    # Optional lightweight timed refresh that does NOT blow away state.
    if st.session_state.get("diag.autorefresh"):
        st.autorefresh(interval=5000, key="diag.autorefresh.tick")

    # Health + Pacing expander
    with st.expander("Health & Pacing", expanded=True):
        cols = st.columns(2)
        with cols[0]:
            _draw_health()
        with cols[1]:
            _draw_pacing()

    # Logs area
    with st.expander("Recent Logs (tail)", expanded=True):
        logs_text = _fetch_logs(limit) if run or st.session_state.get("diag.autorefresh") else None
        if logs_text is None:
            logs_text = _fetch_logs(limit)

        filtered = _apply_filter(logs_text, st.session_state.get("diag.filter") or "")
        st.code(filtered or "—", language="bash")

        # Export buttons
        raw_bytes = filtered.encode("utf-8")
        st.download_button(
            label="Export logs",
            data=raw_bytes,
            file_name=f"gigatrader-logs-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.log",
        )

        # Also show a compact table if the backend returns json objects per line
        df = _maybe_parse_structured_logs(filtered)
        if df is not None and not df.empty:
            st.dataframe(df, use_container_width=True, height=320)

    st.caption(f"API base: {build_url('/')[:-1]}  •  Fetched @ {datetime.utcnow().isoformat()}Z")


def _draw_health():
    try:
        data = get_json("/health")
        if isinstance(data, str):  # backend returned text
            st.text(data.strip())
        else:
            st.metric("Status", data.get("status", "unknown"))
            if errs := data.get("errors"):
                st.error("\n".join(map(str, errs)))
    except Exception as e:
        st.warning(f"Health request failed: {e}\n[{build_url('/health')}]")


def _draw_pacing():
    try:
        data = get_json("/pacing")
        if isinstance(data, str):
            st.text(data.strip())
            return
        # Render common pacing fields if present
        rows: list[tuple[str, Any]] = []
        for key in ("requests_remaining", "reset_in", "window", "limit", "last_request_at"):
            if key in data:
                rows.append((key, data[key]))
        if rows:
            df = pd.DataFrame(rows, columns=["Field", "Value"])
            st.table(df)
        else:
            st.write(data)
    except Exception as e:
        st.warning(f"Pacing request failed: {e}\n[{build_url('/pacing')}]")


def _fetch_logs(limit: int) -> str:
    try:
        # Accept either JSON or raw text. For robustness, ask text explicitly first.
        txt = get_text("/logs/recent", params={"limit": int(limit)})
        return txt if isinstance(txt, str) else str(txt)
    except Exception:
        # Some backends may serve json array of lines
        try:
            res = get_json("/logs/recent", params={"limit": int(limit)})
            if isinstance(res, (list, tuple)):
                return "\n".join(map(str, res))
            return str(res)
        except Exception as e2:
            return f"[warn] failed to fetch logs: {e2}"


def _apply_filter(text: str, needle: str) -> str:
    if not needle:
        return text
    lines = [ln for ln in text.splitlines() if needle.lower() in ln.lower()]
    return "\n".join(lines)


def _maybe_parse_structured_logs(text: str) -> pd.DataFrame | None:
    """
    If logs look like JSON per line, parse into a compact dataframe (level, msg, ts).
    Gracefully degrade on any parse issues.
    """
    items: list[dict] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("{") and ln.endswith("}"):
            try:
                import json
                obj = json.loads(ln)
                row = {
                    "ts": obj.get("ts") or obj.get("time") or obj.get("@timestamp") or "",
                    "level": obj.get("level") or obj.get("lvl") or obj.get("severity") or "",
                    "msg": obj.get("msg") or obj.get("message") or obj.get("event") or ln,
                }
                items.append(row)
            except Exception:
                # silently ignore non-JSON lines
                pass
    if not items:
        return None
    return pd.DataFrame(items)
