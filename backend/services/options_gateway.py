from __future__ import annotations

import logging
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

import pandas as pd

from services.options.adapter import get_option_chain as load_option_chain
from services.options.alpaca_chain import AlpacaChainSource
from services.options.chain import ChainSource, OptionContract


logger = logging.getLogger(__name__)


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:  # noqa: BLE001 - defensive conversion
        return None


def _expiry_to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    try:
        return pd.to_datetime(value).to_pydatetime().date().isoformat()
    except Exception:  # noqa: BLE001 - fallback to string
        return str(value)


class OptionGateway:
    """Provide option chain and greek helpers for the backend routers."""

    def __init__(self, *, chain_source: ChainSource | None = None) -> None:
        self._chain_source = chain_source or AlpacaChainSource()

    async def chain(self, symbol: str) -> Dict[str, Any]:
        """Return an option chain payload shaped for ``ui.state.OptionChain``."""

        try:
            contracts = await self._chain_source.fetch(symbol)
        except Exception as exc:  # noqa: BLE001 - network failure fallback
            logger.warning("option chain fetch failed; falling back to mock", exc_info=exc)
            return self._mock_chain(symbol)

        if not contracts:
            return self._mock_chain(symbol)

        rows = [self._contract_to_row(contract) for contract in contracts]
        return {"symbol": symbol.upper(), "rows": rows}

    async def greeks(self, contract: str) -> Dict[str, Any]:
        symbol, expiry, strike, side = self._parse_contract(contract)
        chain_payload = await self.chain(symbol)
        rows: Iterable[Mapping[str, Any]] = chain_payload.get("rows", [])
        match = self._match_contract(rows, symbol, expiry, strike, side)
        if match is None:
            raise ValueError(f"Option contract not found: {contract}")

        delta = _coerce_float(match.get("delta")) or 0.0
        gamma = _coerce_float(match.get("gamma")) or 0.0
        theta = _coerce_float(match.get("theta")) or 0.0
        vega = _coerce_float(match.get("vega")) or 0.0
        rho = _coerce_float(match.get("rho")) or 0.0

        return {
            "contract": contract,
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "rho": rho,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _contract_to_row(self, contract: OptionContract) -> Dict[str, Any]:
        raw_greeks: Mapping[str, Any] | None = None
        raw = getattr(contract, "raw", None)
        if isinstance(raw, Mapping):
            raw_greeks = raw.get("greeks") if isinstance(raw.get("greeks"), Mapping) else None

        return {
            "symbol": contract.symbol,
            "strike": contract.strike,
            "bid": contract.bid,
            "ask": contract.ask,
            "mid": contract.mid,
            "iv": contract.iv,
            "delta": contract.delta,
            "gamma": raw_greeks.get("gamma") if raw_greeks else None,
            "theta": raw_greeks.get("theta") if raw_greeks else None,
            "vega": raw_greeks.get("vega") if raw_greeks else None,
            "rho": raw_greeks.get("rho") if raw_greeks else None,
            "oi": contract.oi,
            "volume": contract.volume,
            "expiry": _expiry_to_str(contract.expiry),
            "option_type": contract.side,
            "is_liquid": bool(contract.bid and contract.ask and contract.oi),
        }

    def _mock_chain(self, symbol: str) -> Dict[str, Any]:
        as_of = datetime.now(timezone.utc)
        try:
            frame = load_option_chain(symbol, as_of)
        except Exception as exc:  # noqa: BLE001 - fixtures missing
            logger.error("failed to load mock option chain", exc_info=exc)
            return {"symbol": symbol.upper(), "rows": []}

        records = frame.to_dict(orient="records")
        rows = []
        for record in records:
            option_type = record.get("option_type") or record.get("type")
            rows.append(
                {
                    "symbol": record.get("symbol") or symbol.upper(),
                    "strike": _coerce_float(record.get("strike")),
                    "bid": _coerce_float(record.get("bid")),
                    "ask": _coerce_float(record.get("ask")),
                    "mid": _coerce_float(record.get("mid")),
                    "iv": _coerce_float(record.get("iv")),
                    "delta": _coerce_float(record.get("delta")),
                    "gamma": _coerce_float(record.get("gamma")),
                    "theta": _coerce_float(record.get("theta")),
                    "vega": _coerce_float(record.get("vega")),
                    "rho": _coerce_float(record.get("rho")),
                    "oi": record.get("oi"),
                    "volume": record.get("volume"),
                    "expiry": _expiry_to_str(record.get("expiry")),
                    "option_type": option_type,
                    "is_liquid": bool(record.get("oi")) and bool(record.get("volume")),
                }
            )
        return {"symbol": symbol.upper(), "rows": rows}

    @staticmethod
    def _parse_contract(contract: str) -> Tuple[str, Optional[str], Optional[float], Optional[str]]:
        parts = contract.strip().split()
        if not parts:
            raise ValueError("empty contract")
        symbol = parts[0].upper()
        expiry = parts[1] if len(parts) > 1 else None
        strike_side = parts[2] if len(parts) > 2 else None
        strike = None
        side = None
        if isinstance(expiry, str) and expiry.lower() == "next":
            expiry = None
        if strike_side:
            suffix = strike_side[-1].upper()
            if suffix in {"C", "P"}:
                side = "call" if suffix == "C" else "put"
                strike_text = strike_side[:-1]
            else:
                strike_text = strike_side
            try:
                strike = float(strike_text)
            except ValueError:
                strike = None
        return symbol, expiry, strike, side

    @staticmethod
    def _match_contract(
        rows: Iterable[Mapping[str, Any]],
        symbol: str,
        expiry: Optional[str],
        strike: Optional[float],
        side: Optional[str],
    ) -> Optional[Mapping[str, Any]]:
        for row in rows:
            try:
                row_symbol = str(row.get("symbol") or "").upper()
            except Exception:  # noqa: BLE001 - defensive
                row_symbol = ""
            if not row_symbol:
                continue
            if row_symbol != symbol.upper():
                continue
            if side:
                row_side = str(row.get("option_type") or row.get("type") or "").lower()
                if not row_side:
                    continue
                if row_side[0] != side[0]:
                    continue
            if strike is not None:
                row_strike = _coerce_float(row.get("strike"))
                if row_strike is None or abs(row_strike - strike) > 1e-3:
                    continue
            if expiry:
                candidate = row.get("expiry")
                candidate_str = _expiry_to_str(candidate)
                if candidate_str and not candidate_str.startswith(expiry):
                    continue
            return row
        return None


@lru_cache(maxsize=1)
def _cached_gateway() -> OptionGateway:
    return OptionGateway()


def make_option_gateway() -> OptionGateway:
    return _cached_gateway()


__all__ = ["OptionGateway", "make_option_gateway"]
