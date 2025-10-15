"""Notification helpers for operational alerts."""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger("ops.alerts")


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

    log.warning(
        "Slack webhook responded with status %s", response.status_code
    )
    return False
