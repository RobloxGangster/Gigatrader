"""Policy-driven position sizing helper."""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Mapping


_KELLY_ENV_KEYS = ("POLICY_KELLY_FRACTION", "KELLY_FRACTION")
_DAILY_CAP_ENV_KEYS = ("POLICY_DAILY_LOSS_CAP_BPS", "DAILY_LOSS_CAP_BPS")
_ATR_CAP_ENV_KEYS = ("POLICY_ATR_CAP_PCT", "ATR_CAP_PCT")
_ATR_FALLBACK_ENV_KEYS = ("POLICY_ATR_FALLBACK_PCT", "ATR_FALLBACK_PCT")
_DEFAULT_KELLY = 0.25
_DEFAULT_DAILY_CAP_BPS = 200.0
_DEFAULT_ATR_CAP_PCT = 3.0
_DEFAULT_ATR_FALLBACK_PCT = 1.0


def _env_float(keys, default):
    for key in keys:
        value = os.getenv(key)
        if not value:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _copy_context(ctx: Mapping[str, Any] | None) -> Dict[str, Any]:
    if ctx is None:
        return {}
    if isinstance(ctx, dict):
        return dict(ctx)
    return {key: ctx[key] for key in ctx}


def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    if num <= 0:
        return None
    return num


def size_position(ctx: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return recommended position size with diagnostic fields."""

    context = _copy_context(ctx)
    requested_qty = int(float(context.get("qty") or 0))
    price = _positive_float(context.get("price") or context.get("limit_price"))

    account_equity = _positive_float(
        context.get("account_equity")
        or context.get("equity")
        or context.get("portfolio_equity")
        or os.getenv("ACCOUNT_EQUITY_DEFAULT")
    )
    if account_equity is None:
        account_equity = 100_000.0

    alpha_val = context.get("alpha")
    try:
        alpha = float(alpha_val) if alpha_val is not None else 0.0
    except (TypeError, ValueError):
        alpha = 0.0
    if not math.isfinite(alpha):
        alpha = 0.0
    alpha = max(alpha, 0.0)

    proba_val = context.get("proba_up") or context.get("probability")
    try:
        proba = float(proba_val) if proba_val is not None else None
    except (TypeError, ValueError):
        proba = None
    if proba is not None:
        proba = max(0.0, min(1.0, proba))

    kelly_fraction = _env_float(_KELLY_ENV_KEYS, _DEFAULT_KELLY)
    daily_cap_bps = _env_float(_DAILY_CAP_ENV_KEYS, _DEFAULT_DAILY_CAP_BPS)
    atr_cap_pct = _env_float(_ATR_CAP_ENV_KEYS, _DEFAULT_ATR_CAP_PCT)
    atr_fallback_pct = _env_float(_ATR_FALLBACK_ENV_KEYS, _DEFAULT_ATR_FALLBACK_PCT)

    proba_edge = max((proba - 0.5) * 2.0, 0.0) if proba is not None else alpha
    raw_fraction = max(alpha * proba_edge, 0.0)
    risk_fraction = max(raw_fraction * kelly_fraction, 0.0)
    daily_cap_fraction = max(daily_cap_bps / 10_000.0, 0.0)
    capped_by_daily = False
    if risk_fraction > daily_cap_fraction and daily_cap_fraction > 0:
        risk_fraction = daily_cap_fraction
        capped_by_daily = True

    risk_dollars = risk_fraction * account_equity

    stop_price = _positive_float(context.get("stop_price") or context.get("stop"))
    atr_value = _positive_float(context.get("atr") or context.get("atr14") or context.get("risk_per_share"))
    if atr_value is None and price is not None and stop_price is not None:
        atr_value = abs(price - stop_price)
    atr_missing = atr_value is None

    per_unit_risk = atr_value if atr_value is not None else None
    if per_unit_risk is None and price is not None:
        per_unit_risk = max(price * (atr_fallback_pct / 100.0), 0.01)
    if per_unit_risk is None or per_unit_risk <= 0:
        per_unit_risk = 1.0

    atr_capped = False
    if price is not None:
        min_risk = price * (atr_cap_pct / 100.0)
        if per_unit_risk < min_risk:
            per_unit_risk = min_risk
            atr_capped = True

    qty = 0
    if per_unit_risk > 0 and risk_dollars > 0:
        qty = int(risk_dollars / per_unit_risk)

    capped_by_request = False
    if requested_qty > 0 and qty > requested_qty:
        qty = requested_qty
        capped_by_request = True

    max_qty_cap = context.get("max_qty")
    if max_qty_cap is not None:
        try:
            max_cap = int(float(max_qty_cap))
        except (TypeError, ValueError):
            max_cap = None
        if max_cap is not None and max_cap >= 0 and qty > max_cap:
            qty = max_cap
            capped_by_request = True

    reason = "ok"
    if qty <= 0 or risk_fraction <= 0:
        qty = 0
        reason = "kelly_zero" if risk_fraction <= 0 else "sized_zero"
    elif capped_by_request:
        reason = "capped_by_request"
    elif atr_capped:
        reason = "atr_cap"
    elif capped_by_daily:
        reason = "daily_loss_cap"
    elif atr_missing:
        reason = "atr_missing"

    result = {
        "qty": qty,
        "requested_qty": requested_qty,
        "risk_bps": round(risk_fraction * 10_000, 2),
        "risk_dollars": round(risk_dollars, 2),
        "kelly_fraction": kelly_fraction,
        "daily_loss_cap_bps": daily_cap_bps,
        "per_unit_risk": per_unit_risk,
        "atr_used": atr_value if not atr_missing else None,
        "atr_capped": atr_capped,
        "reason": reason,
    }
    return result


__all__ = ["size_position"]
