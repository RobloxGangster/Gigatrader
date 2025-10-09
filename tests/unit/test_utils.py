from __future__ import annotations

from core.utils import idempotency_key


def test_idempotency_key_deterministic() -> None:
    payload = {"symbol": "AAPL", "qty": 10}
    assert idempotency_key(payload) == idempotency_key(payload)
