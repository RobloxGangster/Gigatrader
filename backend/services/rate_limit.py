from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Mapping

_RATE_LIMIT_PATH = Path("runtime") / "pacing.ndjson"


def record_rate_limit(headers: Mapping[str, str] | None) -> None:
    """Persist rate-limit headers for pacing diagnostics."""

    if not headers:
        return
    relevant = {k: headers[k] for k in headers if k.lower().startswith("x-ratelimit")}
    if not relevant:
        return

    limit_raw = headers.get("X-RateLimit-Limit") or headers.get("x-ratelimit-limit")
    remaining_raw = headers.get("X-RateLimit-Remaining") or headers.get("x-ratelimit-remaining")
    reset_raw = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")

    rpm = None
    try:
        if limit_raw and reset_raw:
            limit = float(limit_raw)
            reset_window = float(reset_raw)
            if reset_window > 0:
                rpm = (limit / reset_window) * 60.0
    except (TypeError, ValueError):
        rpm = None

    payload = {
        "ts": time.time(),
        "headers": relevant,
    }
    if rpm is not None:
        payload["rpm"] = rpm
    if remaining_raw is not None:
        payload["remaining"] = remaining_raw

    try:
        _RATE_LIMIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _RATE_LIMIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError:
        # best effort – avoid breaking order flow when filesystem is unavailable
        return


__all__ = ["record_rate_limit"]
