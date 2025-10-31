from __future__ import annotations

from typing import Any

from backend.brokers import AlpacaBrokerAdapter, MockBrokerAdapter
from core.runtime_flags import RuntimeFlags, get_runtime_flags


def _validate_alpaca_flags(flags: RuntimeFlags) -> None:
    missing: list[str] = []
    if not (flags.alpaca_key or "").strip():
        missing.append("ALPACA_KEY_ID")
    if not (flags.alpaca_secret or "").strip():
        missing.append("ALPACA_SECRET_KEY")
    base_url = (flags.alpaca_base_url or "").strip()
    if not base_url:
        missing.append("ALPACA_BASE_URL")
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Alpaca configuration invalid: missing keys or base URL"
            f" ({joined})."
        )


def make_broker_adapter(flags: RuntimeFlags | None = None) -> Any:
    """Return the appropriate broker adapter based on runtime flags."""

    cfg = flags or get_runtime_flags()
    broker = (cfg.broker or "alpaca").lower()

    if broker == "alpaca" and not cfg.mock_mode:
        _validate_alpaca_flags(cfg)
        try:
            adapter = AlpacaBrokerAdapter.from_runtime_flags(cfg)
        except Exception as exc:  # pragma: no cover - configuration errors
            raise RuntimeError("Alpaca configuration invalid: missing keys or base URL") from exc
        return adapter

    if broker == "mock" and not cfg.mock_mode:
        raise RuntimeError(
            "Mock broker selected while MOCK_MODE=false; update BROKER or enable mock mode."
        )

    if cfg.mock_mode or broker == "mock":
        adapter = MockBrokerAdapter()
        setattr(adapter, "dry_run", bool(cfg.dry_run))
        setattr(adapter, "profile", getattr(cfg, "profile", "mock"))
        setattr(adapter, "name", "mock")
        return adapter

    raise ValueError(
        f"Unsupported broker config: broker={cfg.broker}, mock_mode={cfg.mock_mode}"
    )


__all__ = ["make_broker_adapter"]
