import time
from typing import Any, Dict, Optional, Tuple

import requests


def try_get(url: str, timeout: float = 2.0) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Attempt GET <url>. Return (ok, json_or_None, err_or_None).
    ok=True if HTTP 200.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            try:
                return True, resp.json(), None
            except Exception:
                # Non-JSON 200 is technically "ok", still return body text.
                return True, {"raw": resp.text}, None
        else:
            return False, None, f"HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, None, str(e)


def probe_backend(base_url: str, timeout_sec: float = 5.0) -> Tuple[bool, Dict[str, Any], str]:
    """
    Stronger health probe.

    We don't just ping /health. We also try a broker endpoint that should exist
    when the backend is actually alive. If either fails, we consider backend DOWN.

    Returns:
        (is_up, health_info, error_msg)

        is_up: bool
        health_info: dict with whatever we learned (may be partial if down)
        error_msg: non-empty if is_up=False
    """
    deadline = time.time() + timeout_sec
    last_err = ""
    broker_warning: Optional[str] = None

    health_ok = False
    health_payload: Dict[str, Any] = {}

    broker_ok = False

    # poll in a loop for up to timeout_sec
    while time.time() < deadline:
        ok_h, j_h, err_h = try_get(f"{base_url}/health", timeout=min(timeout_sec, 3.0))
        if ok_h and j_h:
            health_ok = True
            health_payload = j_h

        ok_b, j_b, err_b = try_get(f"{base_url}/broker/status", timeout=min(timeout_sec, 3.0))
        if ok_b:
            broker_ok = True
            if j_b:
                health_payload["broker_status"] = j_b
        elif err_b:
            broker_warning = err_b

        if health_ok and broker_ok:
            return True, health_payload, ""

        last_err = err_h or err_b or "backend not responding yet"
        time.sleep(0.5)

    # If we get here, we never got both /health and /broker/status online.
    if health_ok:
        if broker_warning:
            warnings = health_payload.setdefault("warnings", {})
            warnings["broker"] = broker_warning
        return True, health_payload, last_err or ""

    return False, health_payload, last_err or "backend unreachable"
