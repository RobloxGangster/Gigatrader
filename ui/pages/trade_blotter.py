from __future__ import annotations

"""Trade Blotter page."""


from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

from ui.lib.api_client import ApiClient
from ui.lib.page_guard import require_backend
from ui.services.backend import BrokerAPI
from ui.state import AppSessionState

_STATUS_OPTIONS = [
    "filled",
    "partially_filled",
    "accepted",
    "new",
    "canceled",
    "cancelled",
    "rejected",
    "expired",
    "done_for_day",
]
_SIDE_OPTIONS = ["buy", "sell"]
_DEFAULT_LIMIT = 50
_TABLE_COLUMNS = [
    "time",
    "symbol",
    "side",
    "qty",
    "status",
    "avg_fill_price",
    "notional",
]


def _coerce_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _filters_form(state: AppSessionState) -> Dict[str, Any]:
    stored = state.filters or {}
    symbol_default = str(stored.get("symbol") or "")
    sides_default = _coerce_list(stored.get("side"))
    statuses_default = _coerce_list(stored.get("status"))
    start_default = str(stored.get("start") or "")
    end_default = str(stored.get("end") or "")
    limit_default = stored.get("limit", _DEFAULT_LIMIT)
    try:
        limit_default = int(limit_default)
    except (TypeError, ValueError):  # noqa: BLE001 - fallback to default limit
        limit_default = _DEFAULT_LIMIT

    with st.sidebar.expander("Trade Filters", expanded=True):
        with st.form("trade_filters"):
            symbol = st.text_input("Symbol", value=symbol_default, placeholder="AAPL")
            side = st.multiselect("Side", options=_SIDE_OPTIONS, default=sides_default)
            status = st.multiselect(
                "Status",
                options=_STATUS_OPTIONS,
                default=statuses_default,
            )
            start = st.text_input("Start (UTC)", value=start_default, placeholder="2024-01-01")
            end = st.text_input("End (UTC)", value=end_default, placeholder="2024-01-31")
            limit = st.number_input(
                "Limit",
                min_value=1,
                max_value=500,
                value=limit_default,
                step=1,
            )
            submitted = st.form_submit_button("Apply Filters")

    filters: Dict[str, Any] = {
        "symbol": symbol.strip(),
        "side": [s.lower() for s in side],
        "status": [s.lower() for s in status],
        "start": start.strip() or None,
        "end": end.strip() or None,
        "limit": int(limit),
    }

    if submitted or not state.filters:
        state.filters = filters

    return state.filters or filters


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):  # noqa: BLE001 - not a numeric value
        return None


def _orders_to_dataframe(orders: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        time_value = order.get("filled_at") or order.get("submitted_at")
        qty_value = order.get("qty")
        if qty_value in (None, ""):
            qty_value = order.get("filled_qty")
        qty_float = _safe_float(qty_value)

        price_value = (
            order.get("filled_avg_price")
            or order.get("limit_price")
            or order.get("avg_price")
        )
        price_float = _safe_float(price_value)

        notional = None
        if qty_float is not None and price_float is not None:
            notional = round(qty_float * price_float, 2)

        rows.append(
            {
                "time": time_value,
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "qty": qty_float if qty_float is not None else qty_value,
                "status": order.get("status"),
                "avg_fill_price": price_float if price_float is not None else price_value,
                "notional": notional,
            }
        )

    if not rows:
        return pd.DataFrame(columns=_TABLE_COLUMNS)

    df = pd.DataFrame(rows)
    missing_columns = [column for column in _TABLE_COLUMNS if column not in df.columns]
    for column in missing_columns:
        df[column] = None
    return df[_TABLE_COLUMNS]


def render(api: BrokerAPI, state: AppSessionState) -> None:
    st.title("Trade Blotter")
    backend_guard = ApiClient()
    if not require_backend(backend_guard):
        st.stop()

    filters = _filters_form(state)
    empty_df = pd.DataFrame(columns=_TABLE_COLUMNS)

    try:
        trades = api.get_trades(filters)
    except requests.exceptions.HTTPError:
        st.warning("No trade data available right now.")
        st.dataframe(empty_df, width="stretch")
        return
    except requests.exceptions.RequestException:
        st.warning("No trade data available right now.")
        st.dataframe(empty_df, width="stretch")
        return
    except Exception:  # noqa: BLE001 - unexpected errors also surface as warnings
        st.warning("No trade data available right now.")
        st.dataframe(empty_df, width="stretch")
        return

    df = _orders_to_dataframe(trades)
    if df.empty:
        st.info("No trade data matched the selected filters.")
    st.dataframe(df if not df.empty else empty_df, width="stretch")
