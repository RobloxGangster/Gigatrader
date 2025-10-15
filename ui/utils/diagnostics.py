from __future__ import annotations
import json, time, os
from pathlib import Path
from typing import Any, Dict, List, Tuple

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True, parents=True)
UI_DIAG_PATH = LOG_DIR / "ui_diagnostics.ndjson"

def _safe_call(fn, *args, **kwargs) -> Tuple[bool, float, Any, str]:
    t0 = time.perf_counter()
    try:
        resp = fn(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000.0
        return True, dt, resp, ""
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return False, dt, None, f"{type(e).__name__}: {e}"

def _dump(record: Dict[str, Any]) -> None:
    # append as NDJSON
    with UI_DIAG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

def run_ui_diagnostics(api) -> Dict[str, Any]:
    """
    Smoke test the UI <-> backend contract. Returns a structured dict and logs it to logs/ui_diagnostics.ndjson.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results: List[Dict[str, Any]] = []

    checks: List[Tuple[str, Any]] = [
        ("health", lambda: api._request("GET", "/health")),
        ("account", api.get_account if hasattr(api, "get_account") else lambda: api._request("GET", "/alpaca/account")),
        ("orders", api.get_orders),
        ("positions", api.get_positions),
        ("metrics_extended", lambda: api._request("GET", "/metrics/extended")),
        ("ml_status", lambda: api._request("GET", "/ml/status")),
        ("options_chain", lambda: api.get_option_chain("AAPL")),       # works in MOCK_MODE
        ("backtests_list", lambda: api._request("GET", "/backtests")), # may be []
        ("logs_tail", lambda: api.get_logs(10)),
    ]

    passed = 0
    for name, fn in checks:
        ok, ms, payload, err = _safe_call(fn)
        results.append({
            "name": name, "ok": ok, "latency_ms": round(ms, 1),
            "error": err if not ok else None,
            "size_hint": (len(payload) if isinstance(payload, (list, tuple)) else None)
        })
        if ok:
            passed += 1

    summary = {
        "timestamp": ts,
        "total": len(checks),
        "passed": passed,
        "failed": len(checks) - passed,
        "profile": os.getenv("APP_PROFILE") or "unknown",
    }
    record = {"type": "ui_diagnostics", "summary": summary, "results": results}
    _dump(record)
    return record
