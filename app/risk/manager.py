"""Compat shim exposing the runtime RiskManager in the app namespace."""

from services.risk.engine import RiskManager

__all__ = ["RiskManager"]
