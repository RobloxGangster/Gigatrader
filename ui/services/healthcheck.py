import time
import requests


def wait_for_backend_health(base_url: str, timeout_sec: float = 10.0) -> bool:
    """
    Poll /health until we get HTTP 200. Return True if backend is reachable,
    else False after timeout.
    """
    deadline = time.time() + timeout_sec
    last_err = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=1.0)
            if resp.status_code == 200:
                return True
        except Exception as e:
            last_err = e
        time.sleep(0.5)
    # No success
    return False
