"""Utilities for constructing common option spreads with guardrails."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Literal, Mapping, Sequence

from .chain import OptionContract

LegAction = Literal["buy", "sell"]

_OPTION_MULTIPLIER = 100


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_from_raw(contract: OptionContract, key: str) -> float | None:
    raw = contract.raw
    if raw is None:
        return None

    if isinstance(raw, Mapping):
        if key in raw:
            return _to_float(raw.get(key))
        nested = raw.get("greeks")
        if isinstance(nested, Mapping):
            return _to_float(nested.get(key))

    value = getattr(raw, key, None)
    if value is not None:
        return _to_float(value)

    nested = getattr(raw, "greeks", None)
    if nested is not None:
        return _to_float(getattr(nested, key, None))

    return None


def _price_for_action(contract: OptionContract, action: LegAction) -> float:
    price = contract.ask if action == "buy" else contract.bid
    if price is None:
        price = contract.mid
    value = _to_float(price)
    if value is None or value <= 0:
        raise ValueError("invalid_price")
    return float(value)


def _signed_greek(contract: OptionContract, action: LegAction, key: str) -> float | None:
    value = None
    if key == "delta":
        value = _to_float(contract.delta)
    else:
        value = _extract_from_raw(contract, key)

    if value is None:
        return None

    return value if action == "buy" else -value


def _min_liquidity(contracts: Iterable[OptionContract]) -> int:
    liquidity: list[int] = []
    for contract in contracts:
        for attr in (contract.volume, contract.oi):
            if attr is None:
                continue
            if isinstance(attr, (int, float)):
                liquidity.append(int(attr))
    return min(liquidity) if liquidity else 0


@dataclass(slots=True)
class SpreadLeg:
    """Represents a single option leg within a spread."""

    action: LegAction
    contract: OptionContract
    price: float
    ratio: int = 1

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self.contract)
        payload.update(
            {
                "action": self.action,
                "price": self.price,
                "ratio": self.ratio,
            }
        )
        return payload


@dataclass(slots=True)
class SpreadPlan:
    """Structured description of a spread ready for execution."""

    name: str
    quantity: int
    multiplier: int
    legs: Sequence[SpreadLeg]
    pricing: Dict[str, float]
    risk: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "multiplier": self.multiplier,
            "legs": [leg.to_dict() for leg in self.legs],
            "pricing": dict(self.pricing),
            "risk": dict(self.risk),
        }


def _validate_common(long: OptionContract, short: OptionContract) -> None:
    if long.underlying != short.underlying:
        raise ValueError("underlying_mismatch")
    if long.expiry != short.expiry:
        raise ValueError("expiry_mismatch")


def _ensure_liquidity(
    legs: Sequence[OptionContract],
    min_liquidity: int,
) -> None:
    liquidity = _min_liquidity(legs)
    if liquidity < min_liquidity:
        raise ValueError("insufficient_liquidity")


def _check_caps(risk: Mapping[str, float], config: Mapping[str, Any]) -> None:
    max_notional = float(config["options_max_notional_per_expiry"])
    if risk.get("max_loss", 0.0) > max_notional + 1e-9:
        raise ValueError("notional_limit_exceeded")

    max_delta = float(config["delta_bounds"][1])
    total_delta = risk.get("delta")
    if total_delta is not None and abs(float(total_delta)) > max_delta + 1e-9:
        raise ValueError("delta_limit_exceeded")

    vega_limit = float(config["vega_limit"])
    vega = risk.get("vega")
    if vega is not None and abs(float(vega)) > vega_limit + 1e-9:
        raise ValueError("vega_limit_exceeded")

    theta_limit = float(config["theta_limit"])
    theta = risk.get("theta")
    if theta is not None and abs(float(theta)) > theta_limit + 1e-9:
        raise ValueError("theta_limit_exceeded")


def _spread_risk(
    legs: Sequence[SpreadLeg],
    max_loss: float,
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    delta = 0.0
    vega = 0.0
    theta = 0.0
    have_delta = False
    have_vega = False
    have_theta = False
    for leg in legs:
        leg_delta = _signed_greek(leg.contract, leg.action, "delta")
        if leg_delta is not None:
            delta += leg_delta * leg.ratio
            have_delta = True
        leg_vega = _signed_greek(leg.contract, leg.action, "vega")
        if leg_vega is not None:
            vega += leg_vega * leg.ratio
            have_vega = True
        leg_theta = _signed_greek(leg.contract, leg.action, "theta")
        if leg_theta is not None:
            theta += leg_theta * leg.ratio
            have_theta = True

    risk = {
        "max_loss": max_loss,
        "delta": delta if have_delta else None,
        "vega": vega if have_vega else None,
        "theta": theta if have_theta else None,
        "caps": {
            "max_notional": float(config["options_max_notional_per_expiry"]),
            "delta_bounds": tuple(config["delta_bounds"]),
            "vega_limit": float(config["vega_limit"]),
            "theta_limit": float(config["theta_limit"]),
        },
    }
    _check_caps(risk, config)
    return risk


def build_debit_call_spread(
    long_call: OptionContract,
    short_call: OptionContract,
    config: Mapping[str, Any],
    *,
    quantity: int = 1,
    multiplier: int = _OPTION_MULTIPLIER,
) -> SpreadPlan:
    """Construct a debit call spread paying a net premium."""

    _validate_common(long_call, short_call)
    if long_call.side != "call" or short_call.side != "call":
        raise ValueError("invalid_legs")
    if long_call.strike >= short_call.strike:
        raise ValueError("strike_order")

    _ensure_liquidity((long_call, short_call), int(config["min_option_liquidity"]))

    buy_price = _price_for_action(long_call, "buy")
    sell_price = _price_for_action(short_call, "sell")
    net_debit = buy_price - sell_price
    if net_debit <= 0:
        raise ValueError("non_debit")

    spread_width = short_call.strike - long_call.strike
    contract_cost = net_debit * multiplier * quantity
    max_profit = max(spread_width * multiplier * quantity - contract_cost, 0.0)
    breakeven = long_call.strike + net_debit

    legs = (
        SpreadLeg("buy", long_call, price=buy_price),
        SpreadLeg("sell", short_call, price=sell_price),
    )
    risk = _spread_risk(legs, max_loss=contract_cost, config=config)

    pricing = {
        "net_debit": net_debit,
        "max_profit": max_profit,
        "max_loss": contract_cost,
        "breakeven": breakeven,
    }

    return SpreadPlan(
        name="debit_call",
        quantity=quantity,
        multiplier=multiplier,
        legs=legs,
        pricing=pricing,
        risk=risk,
    )


def build_credit_put_spread(
    short_put: OptionContract,
    long_put: OptionContract,
    config: Mapping[str, Any],
    *,
    quantity: int = 1,
    multiplier: int = _OPTION_MULTIPLIER,
) -> SpreadPlan:
    """Construct a credit put spread receiving a net premium."""

    _validate_common(short_put, long_put)
    if short_put.side != "put" or long_put.side != "put":
        raise ValueError("invalid_legs")
    if short_put.strike <= long_put.strike:
        raise ValueError("strike_order")

    _ensure_liquidity((short_put, long_put), int(config["min_option_liquidity"]))

    sell_price = _price_for_action(short_put, "sell")
    buy_price = _price_for_action(long_put, "buy")
    net_credit = sell_price - buy_price
    if net_credit <= 0:
        raise ValueError("non_credit")

    spread_width = short_put.strike - long_put.strike
    max_profit = net_credit * multiplier * quantity
    max_loss = spread_width * multiplier * quantity - max_profit
    breakeven = short_put.strike - net_credit
    if max_loss <= 0:
        raise ValueError("invalid_spread")

    legs = (
        SpreadLeg("sell", short_put, price=sell_price),
        SpreadLeg("buy", long_put, price=buy_price),
    )
    risk = _spread_risk(legs, max_loss=max_loss, config=config)

    pricing = {
        "net_credit": net_credit,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
    }

    return SpreadPlan(
        name="credit_put",
        quantity=quantity,
        multiplier=multiplier,
        legs=legs,
        pricing=pricing,
        risk=risk,
    )


__all__ = [
    "SpreadLeg",
    "SpreadPlan",
    "build_credit_put_spread",
    "build_debit_call_spread",
]
