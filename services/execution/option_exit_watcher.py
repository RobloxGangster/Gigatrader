"""Background task that monitors option positions for configurable exits."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Dict, Optional

from services.execution.engine import ExecutionEngine
from services.execution.types import ExecIntent
from services.options.chain import ChainSource, OptionContract
from services.risk.state import Position, StateProvider


def _extract_mark(metadata: Optional[dict]) -> Optional[float]:
    if not isinstance(metadata, dict):
        return None
    for key in ("market_price", "mark", "mid", "current_price", "last_price"):
        value = metadata.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


class OptionExitWatcher:
    """Poll option positions and trigger exits based on configurable P&L."""

    def __init__(
        self,
        *,
        state: StateProvider,
        exec_engine: ExecutionEngine,
        chain_source: ChainSource | None = None,
        poll_interval: float = 60.0,
        tp_pct: float = 25.0,
        sl_pct: float = 10.0,
        cache_ttl: float = 60.0,
    ) -> None:
        self.state = state
        self.exec = exec_engine
        self.chain = chain_source
        self.poll_interval = max(5.0, float(poll_interval))
        self.tp_pct = float(tp_pct)
        self.sl_pct = float(sl_pct)
        self.cache_ttl = max(10.0, float(cache_ttl))
        self.log = logging.getLogger("gigatrader.option-exit")
        self._inflight: Dict[str, float] = {}
        self._chain_cache: Dict[str, tuple[float, list[OptionContract]]] = {}

    async def run(self, shutdown: asyncio.Event) -> None:
        """Execute the polling loop until shutdown is signalled."""

        while not shutdown.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                self.log.error("option_exit.tick_failed", extra={"error": str(exc)})
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        try:
            positions = self.state.get_positions()
        except NotImplementedError:  # pragma: no cover - interface guard
            positions = {}
        if not positions:
            self._inflight.clear()
            return
        for pos in positions.values():
            await self._evaluate_position(pos)

    async def _evaluate_position(self, position: Position) -> None:
        qty = float(position.qty)
        if not position.is_option or math.isclose(qty, 0.0, abs_tol=1e-9):
            self._inflight.pop(position.symbol, None)
            return
        direction = 1.0 if qty > 0 else -1.0
        entry_price = self._entry_price(position)
        if entry_price <= 0:
            return
        mark = _extract_mark(position.metadata)
        if mark is None:
            mark = await self._fetch_mid(position.symbol)
        if mark is None or mark <= 0:
            return
        gain_pct = (mark - entry_price) / entry_price * 100.0 * direction
        if gain_pct >= self.tp_pct or gain_pct <= -abs(self.sl_pct):
            await self._submit_exit(position, direction)

    def _entry_price(self, position: Position) -> float:
        qty = abs(float(position.qty))
        if qty <= 1e-9:
            return 0.0
        try:
            return abs(float(position.notional)) / qty
        except (TypeError, ValueError):  # pragma: no cover - defensive conversion
            return 0.0

    async def _fetch_mid(self, option_symbol: str) -> Optional[float]:
        if self.chain is None:
            return None
        underlying = self._infer_underlying(option_symbol)
        if not underlying:
            return None
        now = time.time()
        cached = self._chain_cache.get(underlying)
        if cached and now - cached[0] < self.cache_ttl:
            contracts = cached[1]
        else:
            try:
                fetched = await self.chain.fetch(underlying)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - network/SDK errors
                return None
            contracts = list(fetched)
            self._chain_cache[underlying] = (now, contracts)
        for contract in contracts:
            if contract.symbol == option_symbol:
                if contract.mid is not None:
                    return float(contract.mid)
                bid = contract.bid or 0.0
                ask = contract.ask or 0.0
                if bid and ask:
                    return (bid + ask) / 2.0
        return None

    async def _submit_exit(self, position: Position, direction: float) -> None:
        symbol = position.symbol
        in_flight = self._inflight.get(symbol)
        now = time.time()
        if in_flight and now - in_flight < self.poll_interval / 2:
            return
        side = "sell" if direction > 0 else "buy"
        qty = abs(float(position.qty))
        intent = ExecIntent(
            symbol=position.symbol,
            side=side,
            qty=qty,
            asset_class="option",
            option_symbol=position.symbol,
            order_type="market",
            client_tag=f"opt-exit:{position.symbol.lower()}",
        )
        attempts = 0
        while attempts < 2:
            try:
                result = await self.exec.submit(intent)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - adapter/network failure
                attempts += 1
                if attempts >= 2:
                    self.log.error(
                        "option_exit.submit_failed",
                        extra={"symbol": symbol, "error": str(exc)},
                    )
                    break
                await asyncio.sleep(1.0)
                continue
            if result.accepted:
                self._inflight[symbol] = now
                break
            attempts += 1
            if attempts >= 2:
                self.log.warning(
                    "option_exit.rejected",
                    extra={"symbol": symbol, "reason": result.reason},
                )
                break
            await asyncio.sleep(0.5)

    @staticmethod
    def _infer_underlying(option_symbol: str) -> Optional[str]:
        prefix = []
        for ch in option_symbol:
            if ch.isalpha():
                prefix.append(ch)
            else:
                break
        if not prefix:
            return None
        return "".join(prefix)

