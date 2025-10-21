"""Notification helpers for operational alerts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Mapping, Optional

import requests

log = logging.getLogger("ops.alerts")

_AUDIT_DIR = Path(os.getenv("AUDIT_LOG_DIR", "logs"))
_AUDIT_FILE = os.getenv("AUDIT_LOG_FILE", "audit.log")


def _audit_path() -> Path:
    directory = _AUDIT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / _AUDIT_FILE


def _webhook_url() -> Optional[str]:
    return os.getenv("SLACK_WEBHOOK_URL")


def send_slack(text: str) -> bool:
    """Send ``text`` to the configured Slack webhook.

    Returns ``True`` when the POST succeeds and ``False`` when skipped or failed.
    Missing webhook configuration is treated as a no-op.
    """

    url = _webhook_url()
    if not url:
        log.debug("SLACK_WEBHOOK_URL not configured; skipping Slack alert")
        return False

    try:
        response = requests.post(url, json={"text": text}, timeout=5)
    except Exception:  # noqa: BLE001
        log.exception("failed to send Slack alert")
        return False

    if 200 <= response.status_code < 300:
        return True

    log.warning("Slack webhook responded with status %s", response.status_code)
    return False


def audit_log(payload: Mapping[str, object]) -> None:
    """Append ``payload`` as a JSON line to the audit log."""

    try:
        path = _audit_path()
        with path.open("a", encoding="utf-8") as handle:
            json_payload = json.dumps(dict(payload), sort_keys=True)
            handle.write(json_payload + "\n")
    except Exception:  # noqa: BLE001 - logging must not raise
        log.exception("failed to write audit log entry")
