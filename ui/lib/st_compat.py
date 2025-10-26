from __future__ import annotations

import time

import streamlit as st


def auto_refresh(interval_ms: int, key: str):
    """
    Backwards-compatible autorefresh:
    - If Streamlit >= 1.30 has st.autorefresh, use it.
    - Otherwise emulate with a timestamp tick + st.experimental_rerun()
      when the delta exceeds interval.
    """

    if hasattr(st, "autorefresh"):
        return st.autorefresh(interval=interval_ms, key=key)

    now = time.time() * 1000
    tick_key = f"__tick_{key}"
    count_key = f"__count_{key}"
    last = st.session_state.get(tick_key, 0)
    count = int(st.session_state.get(count_key, 0))
    if now - last >= interval_ms:
        st.session_state[tick_key] = now
        count += 1
        st.session_state[count_key] = count
        if hasattr(st, "rerun"):
            st.rerun()
        elif hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
    return count


__all__ = ["auto_refresh"]
