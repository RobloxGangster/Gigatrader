"""Circuit breaker evaluation for trading safety."""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from core.kill_switch import KillSwitch
from services.telemetry.metrics import metrics as telemetry_metrics

log = logging.getLogger("safety.breakers")

# Exposed for monkeypatching in tests.
metrics = telemetry_metrics

_StateDict = Dict[str, Any]

_state_lock = threading.Lock()
_reject_samples: Deque[Tuple[datetime, int]] = deque()
_current_breakers: List[str] = []
_last_trip_breakers: List[str] = []
_last_trip_time: Optional[datetime] = None
_last_checked: Optional[datetime] = None
_observations: Dict[str, Optional[float]] = {}


def _env_float(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


_MAX_DATA_STALE_SEC = _env_float("MAX_DATA_STALE_SEC")
_MAX_REJECTS_PER_MIN = _env_float("MAX_REJECTS_PER_MIN")
_MAX_LATENCY_P95_MS = _env_float("MAX_LATENCY_P95_MS")

_DEFAULT_INTERVAL = 10.0
_interval = _env_float("BREAKERS_CHECK_INTERVAL_SEC") or _DEFAULT_INTERVAL

_limits = {
    "max_data_stale_sec": _MAX_DATA_STALE_SEC,
    "max_rejects_per_min": _MAX_REJECTS_PER_MIN,
    "max_latency_p95_ms": _MAX_LATENCY_P95_MS,
}


def _now_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _compute_reject_rate(now: datetime, total: Optional[float]) -> Optional[float]:
    if total is None:
        _reject_samples.clear()
        return None

    total_int = int(total)

    if _reject_samples and total_int < _reject_samples[-1][1]:
        _reject_samples.clear()

    _reject_samples.append((now, total_int))

    cutoff = now - timedelta(seconds=120)
    while len(_reject_samples) > 1 and _reject_samples[0][0] < cutoff:
        _reject_samples.popleft()

    if len(_reject_samples) < 2:
        return 0.0

    oldest_time, oldest_total = _reject_samples[0]
    delta_seconds = max((now - oldest_time).total_seconds(), 1e-6)
    delta_count = max(total_int - oldest_total, 0)
    return (delta_count / delta_seconds) * 60.0


def _update_state(now: datetime, breakers: List[str], observations: Dict[str, Optional[float]]) -> None:
    global _current_breakers, _last_trip_breakers, _last_trip_time, _last_checked, _observations
    with _state_lock:
        _current_breakers = list(breakers)
        _last_checked = now
        _observations = dict(observations)
        if breakers:
            _last_trip_breakers = list(breakers)
            _last_trip_time = now


def evaluate_breakers(now: datetime) -> List[str]:
    """Return a list of breaker identifiers that should trip."""

    snapshot = metrics.snapshot()
    staleness = snapshot.get("data_staleness_sec")
    latency_info = snapshot.get("order_latency_ms") or {}
    latency_p95 = latency_info.get("p95")
    rejects_info = snapshot.get("order_rejects_total") or {}
    rejects_total = rejects_info.get("total")

    with _state_lock:
        reject_rate = _compute_reject_rate(now, rejects_total)

    breakers: List[str] = []

    if _MAX_DATA_STALE_SEC is not None and staleness is not None:
        try:
            if float(staleness) > _MAX_DATA_STALE_SEC:
                breakers.append("data_stale")
        except (TypeError, ValueError):
            pass

    if _MAX_REJECTS_PER_MIN is not None and reject_rate is not None:
        try:
            if float(reject_rate) > _MAX_REJECTS_PER_MIN:
                breakers.append("reject_spike")
        except (TypeError, ValueError):
            pass

    if _MAX_LATENCY_P95_MS is not None and latency_p95 is not None:
        try:
            if float(latency_p95) > _MAX_LATENCY_P95_MS:
                breakers.append("latency_p95")
        except (TypeError, ValueError):
            pass

    observations = {
        "data_staleness_sec": float(staleness) if staleness is not None else None,
        "rejects_total": float(rejects_total) if rejects_total is not None else None,
        "rejects_per_min": float(reject_rate) if reject_rate is not None else None,
        "latency_p95_ms": float(latency_p95) if latency_p95 is not None else None,
    }
    _update_state(now, breakers, observations)

    return breakers


def enforce_breakers(now: datetime, kill_switch: KillSwitch) -> List[str]:
    """Evaluate breakers and engage the kill switch when needed."""

    trips = evaluate_breakers(now)
    if trips:
        try:
            kill_switch.engage_sync()
        except Exception:  # noqa: BLE001
            log.exception("failed to engage kill switch after breaker trip")
    return trips


def breaker_state() -> _StateDict:
    with _state_lock:
        state = {
            "limits": dict(_limits),
            "current": list(_current_breakers),
            "last_checked": _now_iso(_last_checked),
            "observations": dict(_observations),
            "last_trip": None,
        }
        if _last_trip_breakers:
            state["last_trip"] = {
                "breakers": list(_last_trip_breakers),
                "at": _now_iso(_last_trip_time),
            }
        return state


def is_enabled() -> bool:
    return any(value is not None for value in _limits.values())


def check_interval_seconds() -> float:
    return _interval if _interval > 0 else _DEFAULT_INTERVAL


def _reset_for_tests() -> None:
    with _state_lock:
        _reject_samples.clear()
        _current_breakers.clear()
        _last_trip_breakers.clear()
        global _last_trip_time, _last_checked, _observations
        _last_trip_time = None
        _last_checked = None
        _observations = {}
