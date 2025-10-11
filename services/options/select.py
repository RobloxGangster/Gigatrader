"""Option contract selection utilities."""

from __future__ import annotations

from typing import List, Optional

from services.options.chain import OptionContract, Side


def select_contract(
    contracts: List[OptionContract],
    side: Side,
    target_delta: float,
    delta_band: float,
    min_oi: int,
    min_volume: int,
    min_dte: int,
    max_dte: int,
    price_max: float,
) -> Optional[OptionContract]:
    """Choose the best contract given liquidity and delta constraints."""

    want = target_delta if side == "call" else -target_delta
    lo, hi = want - delta_band, want + delta_band
    candidates: list[OptionContract] = []
    for contract in contracts:
        if contract.side != side:
            continue
        if contract.delta is None or contract.mid is None:
            continue
        if contract.oi is None or contract.volume is None:
            continue
        if contract.oi < min_oi or contract.volume < min_volume:
            continue
        if not (min_dte <= contract.dte <= max_dte):
            continue
        if contract.mid <= 0 or contract.mid > price_max:
            continue
        if lo <= contract.delta <= hi:
            candidates.append(contract)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (abs(c.delta - want), c.dte, -c.volume))
    return candidates[0]
