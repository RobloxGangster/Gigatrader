from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from ui.utils.runtime import get_runtime_flags


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True, parents=True)
UI_DIAG_PATH = LOG_DIR / "ui_diagnostics.ndjson"


def _dump(record: Dict[str, Any]) -> None:
    with UI_DIAG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _safe_call(fn, *args, **kwargs) -> Tuple[str, float, Any, str]:
    t0 = time.perf_counter()
    try:
        resp = fn(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000.0
        if resp is None:
            return "skipped", dt, None, "capability unavailable"
        return "ok", dt, resp, ""
    except requests.HTTPError as exc:  # type: ignore[attr-defined]
        dt = (time.perf_counter() - t0) * 1000.0
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            return "skipped", dt, None, "endpoint unavailable (404)"
        return "fail", dt, None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - diagnostics should surface errors
        dt = (time.perf_counter() - t0) * 1000.0
        return "fail", dt, None, f"{type(exc).__name__}: {exc}"


def _http_json(url: str):
    response = requests.get(url, timeout=3)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.text


def run_ui_diagnostics(api) -> Dict[str, Any]:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    flags = get_runtime_flags(api)
    base = flags.base_url

    common: List[Tuple[str, Any]] = [
        ("orders", api.get_orders),
        ("positions", api.get_positions),
        ("options_chain", lambda: api.get_option_chain("AAPL")),
        ("logs_tail", lambda: api.get_logs(10)),
    ]
    paper_only: List[Tuple[str, Any]] = [
        ("health", lambda: _http_json(f"{base}/health")),
        ("account", lambda: _http_json(f"{base}/alpaca/account")),
        ("metrics_extended", lambda: _http_json(f"{base}/metrics/extended")),
        ("ml_status", lambda: _http_json(f"{base}/ml/status")),
        ("backtests_list", lambda: _http_json(f"{base}/backtests")),
    ]
    checks = common + (paper_only if not flags.mock_mode else [(name, lambda: None) for name, _ in paper_only])

    results: List[Dict[str, Any]] = []
    passed = failed = skipped = 0

    for name, fn in checks:
        status, ms, payload, err = _safe_call(fn)
        results.append(
            {
                "name": name,
                "ok": status == "ok",
                "skipped": status == "skipped",
                "latency_ms": round(ms, 1),
                "error": (err or None) if status != "ok" else None,
                "size_hint": len(payload) if isinstance(payload, (list, tuple)) else None,
            }
        )
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
