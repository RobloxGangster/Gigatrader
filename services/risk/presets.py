"""Risk configuration presets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPreset:
    daily_loss_limit: float
    per_trade_risk_pct: float
    max_positions: int
    max_notional: float
    max_symbol_notional: float
    cooldown_sec: int
    options_min_oi: int
    options_min_volume: int
    options_delta_min: float
    options_delta_max: float


PRESETS = {
    "safe": RiskPreset(500.0, 0.25, 3, 25_000.0, 7_500.0, 300, 200, 100, 0.20, 0.35),
    "balanced": RiskPreset(1_000.0, 0.5, 5, 50_000.0, 15_000.0, 180, 150, 75, 0.18, 0.40),
    "high": RiskPreset(2_000.0, 1.0, 8, 100_000.0, 30_000.0, 120, 100, 50, 0.15, 0.45),
}
