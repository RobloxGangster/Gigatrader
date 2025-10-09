"""Reusable table helpers for pagination and exports."""
from __future__ import annotations

import io
from typing import Any, Dict, Iterable, List

import pandas as pd
import streamlit as st


def render_table(name: str, rows: Iterable[Dict[str, Any]], *, page_size: int = 25) -> None:
    """Render a paginated table with CSV download support."""
    rows_list = list(rows)
    if not rows_list:
        st.info("No data available.")
        return

    df = pd.DataFrame(rows_list)
    total_rows = len(df)
    page = st.session_state.get(f"{name}_page", 0)
    start = page * page_size
    end = start + page_size

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.caption(f"Showing {start + 1}-{min(end, total_rows)} of {total_rows}")
    with col2:
        if st.button("Prev", disabled=page == 0, key=f"{name}_prev"):
            page = max(page - 1, 0)
            st.session_state[f"{name}_page"] = page
            st.experimental_rerun()
    with col3:
        if st.button("Next", disabled=end >= total_rows, key=f"{name}_next"):
            page = min(page + 1, (total_rows - 1) // page_size)
            st.session_state[f"{name}_page"] = page
            st.experimental_rerun()

    st.dataframe(df.iloc[start:end])

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    st.download_button(
        "Export CSV",
        buffer.getvalue().encode("utf-8"),
        file_name=f"{name}.csv",
        mime="text/csv",
        key=f"{name}_download",
    )

