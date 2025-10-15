from __future__ import annotations
import json, time, os, requests
from pathlib import Path
from typing import Any, Dict, List, Tuple
from ui.utils.runtime import get_runtime_flags

LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True, parents=True)
UI_DIAG_PATH = LOG_DIR / "ui_diagnostics.ndjson"

def _dump(record: Dict[str, Any]) -> None:
    with UI_DIAG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

def _safe_call(fn, *args, **kwargs) -> Tuple[str, float, Any, str]:
    t0 = time.perf_counter()
    try:
        resp = fn(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000.0
        if resp is None:
            return "skipped", dt, None, "capability unavailable"
        return "ok", dt, resp, ""
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return "fail", dt, None, f"{type(e).__name__}: {e}"

def _http_json(url: str) -> Any:
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text

def run_ui_diagnostics(api) -> Dict[str, Any]:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    flags = get_runtime_flags(api)
    base = flags.base_url

    # Checks that are safe in both modes
    checks: List[Tuple[str, Any]] = [
        ("orders",            api.get_orders),
        ("positions",         api.get_positions),
        ("options_chain",     lambda: api.get_option_chain("AAPL")),
        ("logs_tail",         lambda: api.get_logs(10)),
    ]

    # Backend-only checks: run in PAPER; SKIP in MOCK
    if not flags.mock_mode:
        checks.extend([
            ("health",            lambda: _http_json(f"{base}/health")),
            ("account",           getattr(api, "get_account", None) or (lambda: _http_json(f"{base}/alpaca/account"))),
            ("metrics_extended",  lambda: _http_json(f"{base}/metrics/extended")),
            ("ml_status",         lambda: _http_json(f"{base}/ml/status")),
            ("backtests_list",    lambda: _http_json(f"{base}/backtests")),
        ])
    else:
        checks.extend([
            ("health",            lambda: None),
            ("account",           lambda: None),
            ("metrics_extended",  lambda: None),
            ("ml_status",         lambda: None),
            ("backtests_list",    lambda: None),
        ])

    results: List[Dict[str, Any]] = []
    passed = failed = skipped = 0

    for name, fn in checks:
        status, ms, payload, err = _safe_call(fn)
        results.append({
            "name": name,
            "ok": (status == "ok"),
            "skipped": (status == "skipped"),
            "latency_ms": round(ms, 1),
            "error": err if status == "fail" else None,
            "size_hint": (len(payload) if isinstance(payload, (list, tuple)) else None),
        })
        if status == "ok":
            passed += 1
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1

    summary = {
        "timestamp": ts,
        "mode": "MOCK" if flags.mock_mode else "PAPER",
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }
    record = {"type": "ui_diagnostics", "summary": summary, "results": results}
    _dump(record)
    return record
