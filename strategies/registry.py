from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, Any

AlphaFn = Callable[[Dict[str, Any]], float]  # returns [-1, 1]


@dataclass
class AlphaSpec:
    name: str
    weight: float
    fn: AlphaFn
    enabled: bool = True


class StrategyRegistry:
    def __init__(self):
        self._alphas: Dict[str, AlphaSpec] = {}

    def register(self, name: str, fn: AlphaFn, weight: float = 1.0, enabled: bool = True):
        self._alphas[name] = AlphaSpec(name=name, fn=fn, weight=weight, enabled=enabled)

    def set_weight(self, name: str, weight: float):
        self._alphas[name].weight = weight

    def enable(self, name: str, enabled: bool = True):
        self._alphas[name].enabled = enabled

    def blend(self, ctx: Dict[str, Any]) -> float:
        num, den = 0.0, 0.0
        for spec in self._alphas.values():
            if not spec.enabled:
                continue
            a = float(spec.fn(ctx))
            num += spec.weight * a
            den += abs(spec.weight)
        return 0.0 if den == 0 else num / den


# Example alpha stubs:
def alpha_intraday_momo(ctx):
    return ctx.get("momo_score", 0.0)


def alpha_mean_reversion(ctx):
    return ctx.get("mr_score", 0.0)


def alpha_breakout(ctx):
    return ctx.get("brk_score", 0.0)


def alpha_swing_options(ctx):
    return ctx.get("swing_score", 0.0)
