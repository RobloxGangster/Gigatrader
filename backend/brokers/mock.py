from __future__ import annotations

from app.execution.adapters import MockBrokerAdapter as _MockBrokerAdapter


class MockBrokerAdapter(_MockBrokerAdapter):
    """Compatibility shim so the backend can import a consistent class name."""

    def __init__(self) -> None:
        super().__init__()
        setattr(self, "name", "mock")
        setattr(self, "profile", "mock")
        setattr(self, "dry_run", False)
        setattr(self, "paper", True)

    # The backend historically expects ``fetch_*`` helpers. Provide thin wrappers
    # for compatibility so existing code paths do not need to branch on the
    # adapter type.
    def fetch_account(self):  # pragma: no cover - simple delegation
        return self.get_account()

    def fetch_positions(self):  # pragma: no cover - simple delegation
        return self.list_positions()

    def fetch_orders(self, *, status: str = "all", limit: int = 50):  # pragma: no cover
        return self.list_orders(status=status, limit=limit)
