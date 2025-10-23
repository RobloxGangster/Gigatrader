from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.runtime_flags import RuntimeFlags, require_alpaca_keys

from .alpaca_adapter import AlpacaAdapter


class BrokerAdapter(Protocol):
    def status(self) -> dict[str, object]:  # pragma: no cover - protocol
        ...


@dataclass
class MockBrokerAdapter:
    """Minimal mock adapter used when running in ``MOCK_MODE``."""

    def status(self) -> dict[str, object]:
        return {"broker": "mock", "online": True}

    # The order routing path exercises these helpers during unit tests.
    def place_order(self, payload: dict[str, object]) -> dict[str, object]:  # pragma: no cover - trivial
        return {
            "id": "mock-order",
            "client_order_id": payload.get("client_order_id"),
            "status": "filled",
        }

    def cancel_order(self, order_id: str) -> bool:  # pragma: no cover - trivial
        return True

    def list_orders(self, *, status: str = "all", limit: int = 50) -> list[dict[str, object]]:  # pragma: no cover - trivial
        return []

    def list_positions(self) -> list[dict[str, object]]:  # pragma: no cover - trivial
        return []

    def get_account(self) -> dict[str, object]:  # pragma: no cover - trivial
        return {"equity": 0.0, "cash": 0.0}


def make_broker_adapter(flags: RuntimeFlags) -> BrokerAdapter:
    if flags.mock_mode:
        return MockBrokerAdapter()
    require_alpaca_keys()
    adapter = AlpacaAdapter(
        base_url=flags.alpaca_base_url,
        key_id=flags.alpaca_key,
        secret_key=flags.alpaca_secret,
    )
    setattr(adapter, "paper", bool(flags.paper_trading))
    return adapter
