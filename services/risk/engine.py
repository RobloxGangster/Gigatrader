"""Configurable risk manager for the trading hot path."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from core.kill_switch import KillSwitch
from services.risk.presets import PRESETS, RiskPreset
from services.risk.state import Position, StateProvider


@dataclass(slots=True)
class Proposal:
    """Proposed order intent prior to broker submission."""

    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    price: float  # expected fill
    is_option: bool = False
    delta: Optional[float] = None
    est_sl: Optional[float] = None  # optional stop price
    est_tp: Optional[float] = None  # optional target price


@dataclass(slots=True)
class Decision:
    """Risk decision describing whether a proposal is allowed."""

    allow: bool
    reason: str
    max_qty: Optional[float] = None


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class RiskManager:
    """Central risk engine enforcing static caps before broker interaction."""

    def __init__(self, state: StateProvider, kill_switch: KillSwitch | None = None) -> None:
        profile = os.getenv("RISK_PROFILE", "balanced").strip().lower()
        preset: RiskPreset = PRESETS.get(profile, PRESETS["balanced"])
        self.cfg = RiskPreset(
            daily_loss_limit=_env_float("DAILY_LOSS_LIMIT", preset.daily_loss_limit),
            per_trade_risk_pct=_env_float("PER_TRADE_RISK_PCT", preset.per_trade_risk_pct),
            max_positions=_env_int("MAX_POSITIONS", preset.max_positions),
            max_notional=_env_float("MAX_NOTIONAL", preset.max_notional),
            max_symbol_notional=_env_float("MAX_SYMBOL_NOTIONAL", preset.max_symbol_notional),
            cooldown_sec=_env_int("COOLDOWN_SEC", preset.cooldown_sec),
            options_min_oi=_env_int("OPTIONS_MIN_OI", preset.options_min_oi),
            options_min_volume=_env_int("OPTIONS_MIN_VOLUME", preset.options_min_volume),
            options_delta_min=_env_float("OPTIONS_DELTA_MIN", preset.options_delta_min),
            options_delta_max=_env_float("OPTIONS_DELTA_MAX", preset.options_delta_max),
        )
        self.state = state
        self.kill_switch = kill_switch or KillSwitch()

    def _risk_budget_dollars(self) -> float:
        """Return the per-trade dollar risk budget."""

        equity: Optional[float]
        try:
            equity = self.state.get_account_equity()
        except Exception:
            equity = None
        base = equity if equity is not None and equity > 0 else self.cfg.max_notional
        return (self.cfg.per_trade_risk_pct / 100.0) * base

    def _additional_notional(self, proposal: Proposal, position: Optional[Position]) -> float:
        """Return the incremental notional the trade would add."""

        side = proposal.side.lower()
        if side not in {"buy", "sell"}:
            return abs(proposal.qty * proposal.price)

        direction = 1.0 if side == "buy" else -1.0
        existing_qty = position.qty if position is not None else 0.0
        post_qty = existing_qty + direction * proposal.qty
        additional_qty = max(0.0, abs(post_qty) - abs(existing_qty))
        return additional_qty * proposal.price

    def pre_trade_check(
        self,
        proposal: Proposal,
        *,
        symbol_oi: Optional[int] = None,
        symbol_vol: Optional[int] = None,
    ) -> Decision:
        try:
            ks = getattr(self, "kill_switch", None)
            if ks is None:
                ks = KillSwitch()
                self.kill_switch = ks
            if getattr(ks, "engaged_sync", None) and ks.engaged_sync():
                return Decision(False, "kill_switch_active")
        except Exception:
            pass

        if _env_bool("KILL_SWITCH", False):
            return Decision(False, "kill_switch_active")

        day_pnl = self.state.get_day_pnl()
        if day_pnl <= -abs(self.cfg.daily_loss_limit):
            return Decision(False, "daily_loss_limit_breached")

        if proposal.qty <= 0 or proposal.price <= 0:
            return Decision(False, "invalid_qty_or_price")

        positions = self.state.get_positions()
        existing_position = positions.get(proposal.symbol)
        additional_notional = self._additional_notional(proposal, existing_position)

        portfolio_notional = self.state.get_portfolio_notional()
        if portfolio_notional + additional_notional > self.cfg.max_notional + 1e-9:
            return Decision(False, "max_portfolio_notional_exceeded")

        open_positions = sum(1 for pos in positions.values() if abs(pos.qty) > 0)
        if proposal.symbol not in positions and open_positions >= self.cfg.max_positions:
            return Decision(False, "max_positions_exceeded")

        existing_symbol_notional = abs(existing_position.notional) if existing_position else 0.0
        if existing_symbol_notional + additional_notional > self.cfg.max_symbol_notional + 1e-9:
            return Decision(False, "max_symbol_notional_exceeded")

        last_age = getattr(self.state, "last_trade_age", None)
        if callable(last_age):
            age = last_age(proposal.symbol)
            if age is not None and age < self.cfg.cooldown_sec:
                return Decision(False, "cooldown_active")

        if proposal.is_option:
            if symbol_oi is not None and symbol_oi < self.cfg.options_min_oi:
                return Decision(False, "options_min_oi_not_met")
            if symbol_vol is not None and symbol_vol < self.cfg.options_min_volume:
                return Decision(False, "options_min_volume_not_met")
            if proposal.delta is not None and not (
                self.cfg.options_delta_min <= abs(proposal.delta) <= self.cfg.options_delta_max
            ):
                return Decision(False, "options_delta_out_of_bounds")

        if proposal.est_sl is not None:
            risk_per_share = abs(proposal.price - proposal.est_sl)
            if risk_per_share <= 0:
                return Decision(False, "invalid_stop_for_risk")
            risk_budget = self._risk_budget_dollars()
            if risk_budget <= 0:
                return Decision(False, "per_trade_risk_exceeded", max_qty=0.0)
            max_qty = max(risk_budget / risk_per_share, 0.0)
            if proposal.qty - max_qty > 1e-9:
                return Decision(False, "per_trade_risk_exceeded", max_qty=max_qty)

        return Decision(True, "ok")
