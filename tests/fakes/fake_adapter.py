"""Fake execution adapter used for unit tests."""

from __future__ import annotations

from typing import Any, Dict, Optional


class FakeAdapter:
    """Simple adapter double that records calls and echoes identifiers."""

    def __init__(self) -> None:
        self.submits: list[Any] = []
        self.cancels: list[Any] = []
        self.replaces: list[tuple[Any, Dict[str, Any]]] = []
        self._counter = 0

    async def submit_order(self, payload: Any) -> Dict[str, Any]:
        self.submits.append(payload)
        self._counter += 1
        client_order_id = self._coerce_client_order_id(payload)
        order_id = f"order-{self._counter}"
        return {
            "id": order_id,
            "client_order_id": client_order_id,
            "status": "accepted",
        }

    async def cancel_order(self, order_id: Any) -> None:
        self.cancels.append(order_id)

    async def replace_order(self, order_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.replaces.append((order_id, payload))
        return {"id": order_id, "status": "replaced"}

    @staticmethod
    def _coerce_client_order_id(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            return payload.get("client_order_id")
        return getattr(payload, "client_order_id", None)
