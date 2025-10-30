"""Broker service factory utilities."""

from __future__ import annotations

from core.config import Settings

from .alpaca_adapter import AlpacaBrokerAdapter


def make_broker(settings: Settings) -> AlpacaBrokerAdapter:
    broker = settings.broker
    if broker != "alpaca":
        raise ValueError(f"Unsupported broker: {broker}")
    return AlpacaBrokerAdapter(settings)


__all__ = ["make_broker", "AlpacaBrokerAdapter"]
