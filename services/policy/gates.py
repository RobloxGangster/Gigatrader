"""Pre-trade gating logic combining alpha signals and ML probabilities."""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Tuple

from strategies.registry import (
    StrategyRegistry,
    alpha_breakout,
    alpha_intraday_momo,
    alpha_mean_reversion,
    alpha_swing_options,
)


_REGISTRY = StrategyRegistry()
_REGISTRY.register("intraday_momo", alpha_intraday_momo)
_REGISTRY.register("mean_reversion", alpha_mean_reversion)
_REGISTRY.register("breakout", alpha_breakout)
_REGISTRY.register("swing_options", alpha_swing_options)

_ALPHA_ENV_KEYS = ("POLICY_ALPHA_MIN", "ALPHA_MIN")
_PROBA_ENV_KEYS = ("POLICY_PROBA_MIN", "PROBA_MIN")
_DEFAULT_ALPHA_MIN = 0.15
_DEFAULT_PROBA_MIN = 0.55


def _env_float(keys: Tuple[str, ...], default: float) -> float:
    for key in keys:
        value = os.getenv(key)
        if not value:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _alpha_min() -> float:
    return _env_float(_ALPHA_ENV_KEYS, _DEFAULT_ALPHA_MIN)


def _proba_min() -> float:
    return _env_float(_PROBA_ENV_KEYS, _DEFAULT_PROBA_MIN)


def _normalise_probability(value: Any) -> float | None:
    if value is None:
        return None
    try:
        prob = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, prob))


def _copy_context(ctx: Mapping[str, Any] | None) -> Dict[str, Any]:
    if ctx is None:
        return {}
    if isinstance(ctx, dict):
        return dict(ctx)
    return {key: ctx[key] for key in ctx}


def should_trade(ctx: Mapping[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    """Return whether the trade should proceed along with diagnostic context."""

    context = _copy_context(ctx)
    context.setdefault("symbol", context.get("symbol"))
    context.setdefault("side", context.get("side", "neutral"))

    blended_alpha = float(_REGISTRY.blend(context))
    provided_alpha = context.get("alpha")
    try:
        provided_alpha = float(provided_alpha) if provided_alpha is not None else None
    except (TypeError, ValueError):
        provided_alpha = None
    alpha_value = provided_alpha if provided_alpha is not None else blended_alpha

    proba_value = _normalise_probability(
        context.get("proba_up", context.get("probability"))
    )
    context["proba_up"] = proba_value

    alpha_min = _alpha_min()
    proba_min = _proba_min()

    allow = True
    failure_reasons: list[str] = []
    info_reasons: list[str] = []

    if alpha_value is None:
        info_reasons.append("alpha_missing")
    else:
        if alpha_value < alpha_min:
            allow = False
            failure_reasons.append("alpha_below_min")
    context["alpha"] = alpha_value
    context["alpha_blend"] = blended_alpha
    context["alpha_min"] = alpha_min
    context["alpha_status"] = (
        "missing"
        if alpha_value is None
        else ("pass" if alpha_value >= alpha_min else "fail")
    )

    if proba_value is None:
        info_reasons.append("proba_missing")
    else:
        if proba_value < proba_min:
            allow = False
            failure_reasons.append("proba_below_min")
    context["proba_min"] = proba_min
    context["proba_status"] = (
        "missing"
        if proba_value is None
        else ("pass" if proba_value >= proba_min else "fail")
    )

    if allow:
        reason_codes = ["ok"]
    else:
        reason_codes = failure_reasons or ["blocked"]
    reason_codes.extend(info_reasons)

    context["reason_codes"] = reason_codes
    context["decision"] = "allow" if allow else "block"

    return allow, context


__all__ = ["should_trade"]
