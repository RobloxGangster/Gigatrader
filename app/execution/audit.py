"""Append-only audit log utilities for reconciliation events."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List


class AuditLog:
    """Simple thread-safe append-only JSON-lines log."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, event: Dict[str, Any]) -> None:
        """Append a single event as a JSON line."""

        line = json.dumps(event, sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")

    def tail(self, n: int = 50) -> List[Dict[str, Any]]:
        """Return the latest ``n`` events (oldest first)."""

        if n <= 0:
            return []

        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()

        events: List[Dict[str, Any]] = []
        for raw in lines[-n:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events


__all__ = ["AuditLog"]

