"""Helpers for loading pacing telemetry snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

_DEFAULT_WINDOW_SECONDS = 60
_DEFAULT_MAX_RPM = 0.0
_HISTORY_LIMIT = 360


@dataclass(slots=True)
class _PacingSnapshot:
    rpm: float = 0.0
    backoff_events: int = 0
    retries: int = 0
    max_rpm: float = _DEFAULT_MAX_RPM
    window_seconds: int = _DEFAULT_WINDOW_SECONDS
    history: List[float] | None = None


_PACING_JSON_PATHS: Iterable[Path] = (
    Path("runtime") / "pacing.json",
    Path("logs") / "pacing.json",
)

_PACING_NDJSON_PATHS: Iterable[Path] = (
    Path("runtime") / "pacing.ndjson",
    Path("logs") / "pacing.ndjson",
)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_history(values: Iterable[Any]) -> List[float]:
    sanitized: List[float] = []
    for value in values:
        coerced = _coerce_float(value)
        if coerced is None:
            continue
        sanitized.append(coerced)
        if len(sanitized) >= _HISTORY_LIMIT:
            break
    return sanitized


def _merge_snapshot(snapshot: _PacingSnapshot, payload: Dict[str, Any]) -> None:
    rpm = _coerce_float(payload.get("rpm"))
    if rpm is not None:
        snapshot.rpm = rpm

    backoff_events = _coerce_int(payload.get("backoff_events"))
    if backoff_events is not None:
        snapshot.backoff_events = max(backoff_events, 0)

    retries = _coerce_int(payload.get("retries"))
    if retries is not None:
        snapshot.retries = max(retries, 0)

    max_rpm = _coerce_float(payload.get("max_rpm"))
    if max_rpm is not None:
        snapshot.max_rpm = max(max_rpm, 0.0)

    window_seconds = _coerce_int(payload.get("window_seconds"))
    if window_seconds is not None and window_seconds > 0:
        snapshot.window_seconds = window_seconds

    history = payload.get("history")
    if isinstance(history, (list, tuple)):
        sanitized_history = _sanitize_history(history)
        if sanitized_history:
            snapshot.history = sanitized_history


def _load_json_payload(path: Path) -> Dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        return payload
    return None


def _load_ndjson_payload(path: Path) -> Dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    snapshot: Dict[str, Any] = {}
    history: List[float] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        snapshot.update(payload)
        if "history" in payload and isinstance(payload["history"], (list, tuple)):
            history = _sanitize_history(payload["history"])
        else:
            rpm = _coerce_float(payload.get("rpm"))
            if rpm is not None:
                history.append(rpm)
    if history:
        snapshot["history"] = history[-_HISTORY_LIMIT:]
    return snapshot or None


def load_pacing_snapshot() -> Dict[str, Any]:
    """Return the latest pacing telemetry snapshot.

    The loader inspects a few well-known locations where the trading runtime
    persists pacing diagnostics. The locations are intentionally loose so the
    backend can serve useful data even when the runtime has not yet emitted a
    dedicated snapshot. Any malformed payloads are ignored and a safe default is
    returned.
    """

    snapshot = _PacingSnapshot()

    for path in _PACING_JSON_PATHS:
        if not path.exists():
            continue
        payload = _load_json_payload(path)
        if payload is None:
            continue
        _merge_snapshot(snapshot, payload)
        break

    else:
        for path in _PACING_NDJSON_PATHS:
            if not path.exists():
                continue
            payload = _load_ndjson_payload(path)
            if payload is None:
                continue
            _merge_snapshot(snapshot, payload)
            break

    history = snapshot.history or []
    return {
        "rpm": snapshot.rpm,
        "backoff_events": snapshot.backoff_events,
        "retries": snapshot.retries,
        "max_rpm": snapshot.max_rpm,
        "window_seconds": snapshot.window_seconds,
        "history": history,
    }

