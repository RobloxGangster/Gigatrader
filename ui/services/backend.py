"""Backend client abstractions for the Gigatrader UI."""

from __future__ import annotations

import json
import os
import random
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

import requests
from pydantic import BaseModel, Field

from .config import api_base_url, mock_mode
from ui.state import (
    EquityPoint,
    Greeks,
    Indicators,
    LogEvent,
    OptionChain,
    Order,
    PacingStats,
    Position,
    ReportSummary,
    RiskSnapshot,
    RunInfo,
    Trade,
)

_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"
_DEFAULT_TIMEOUT = 8


class BackendError(RuntimeError):
    """Raised when the backend cannot fulfil a request."""


class BrokerAPI(Protocol):
    """Protocol describing backend interactions required by the UI."""

    def get_status(self) -> Dict[str, Any]: ...

    def start_paper(self, preset: Optional[str] = None) -> Dict[str, Any]: ...

    def start_live(self, preset: Optional[str] = None) -> Dict[str, Any]: ...

    def stop_all(self) -> Dict[str, Any]: ...

    def flatten_and_halt(self) -> Dict[str, Any]: ...

    def get_equity_curve(self, run_id: Optional[str] = None) -> List[EquityPoint]: ...

    def get_risk_snapshot(self) -> RiskSnapshot: ...

    def get_orders(self) -> List[Order]: ...

    def get_positions(self) -> List[Position]: ...

    def get_trades(self, filters: Optional[Dict[str, Any]] = None) -> List[Trade]: ...

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> OptionChain: ...

    def get_greeks(self, contract: str) -> Greeks: ...

    def get_indicators(self, symbol: str, lookback: int) -> Indicators: ...

    def apply_strategy_params(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...

    def get_backtest_runs(self) -> List[RunInfo]: ...

    def get_backtest_report(self, run_id: str) -> ReportSummary: ...

    def get_logs(self, tail: int, level: Optional[str] = None) -> List[LogEvent]: ...

    def get_pacing_stats(self) -> PacingStats: ...


def _build_trace_headers() -> Dict[str, str]:
    trace_id = f"ui-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    return {"X-Trace-Id": trace_id}


def _load_json_fixture(name: str) -> Any:
    path = _FIXTURE_ROOT / f"{name}.json"
    if not path.exists():
        raise BackendError(f"Missing fixture: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class RealAPI:
    """HTTP backed API implementation."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or api_base_url()).rstrip("/")
        self.session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = _build_trace_headers()
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json_payload,
                headers=headers,
                timeout=_DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - defensive branch
            raise BackendError(str(exc)) from exc
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    def get_status(self) -> Dict[str, Any]:
        return self._request("GET", "/status")

    def start_paper(self, preset: Optional[str] = None) -> Dict[str, Any]:
        payload = {"preset": preset} if preset else None
        return self._request("POST", "/paper/start", json_payload=payload)

    def start_live(self, preset: Optional[str] = None) -> Dict[str, Any]:
        payload = {"preset": preset} if preset else None
        return self._request("POST", "/live/start", json_payload=payload)

    def stop_all(self) -> Dict[str, Any]:
        return self._request("POST", "/paper/stop")

    def flatten_and_halt(self) -> Dict[str, Any]:
        return self._request("POST", "/paper/flatten")

    def get_equity_curve(self, run_id: Optional[str] = None) -> List[EquityPoint]:
        payload = self._request("GET", "/equity", params={"run_id": run_id} if run_id else None)
        return [EquityPoint(**item) for item in payload]

    def get_risk_snapshot(self) -> RiskSnapshot:
        payload = self._request("GET", "/risk")
        return RiskSnapshot(**payload)

    def get_orders(self) -> List[Order]:
        payload = self._request("GET", "/orders")
        return [Order(**item) for item in payload]

    def get_positions(self) -> List[Position]:
        payload = self._request("GET", "/positions")
        return [Position(**item) for item in payload]

    def get_trades(self, filters: Optional[Dict[str, Any]] = None) -> List[Trade]:
        payload = self._request("GET", "/trades", params=filters)
        return [Trade(**item) for item in payload]

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> OptionChain:
        payload = self._request(
            "GET", "/options/chain", params={"symbol": symbol, "expiry": expiry}
        )
        return OptionChain(**payload)

    def get_greeks(self, contract: str) -> Greeks:
        payload = self._request("GET", "/options/greeks", params={"contract": contract})
        return Greeks(**payload)

    def get_indicators(self, symbol: str, lookback: int) -> Indicators:
        payload = self._request(
            "GET", "/indicators", params={"symbol": symbol, "lookback": lookback}
        )
        return Indicators(**payload)

    def apply_strategy_params(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/strategy/params", json_payload=payload)

    def get_backtest_runs(self) -> List[RunInfo]:
        payload = self._request("GET", "/backtests")
        return [RunInfo(**item) for item in payload]

    def get_backtest_report(self, run_id: str) -> ReportSummary:
        payload = self._request("GET", "/backtests/report", params={"run_id": run_id})
        return ReportSummary(**payload)

    def get_logs(self, tail: int, level: Optional[str] = None) -> List[LogEvent]:
        payload = self._request(
            "GET", "/logs", params={"tail": tail, "level": level} if level else {"tail": tail}
        )
        return [LogEvent(**item) for item in payload]

    def get_pacing_stats(self) -> PacingStats:
        payload = self._request("GET", "/pacing")
        return PacingStats(**payload)


class _MockState(BaseModel):
    run_id: Optional[str] = None
    status: Dict[str, Any]
    params: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class MockAPI:
    """Deterministic fixture based API implementation for local development."""

    def __init__(self) -> None:
        seed = int(os.getenv("MOCK_SEED", "42"))
        self.random = random.Random(seed)
        status = _load_json_fixture("status")
        status.setdefault("paper", True)
        status.setdefault("halted", False)
        self._state = _MockState(status=status)

    # helpers -----------------------------------------------------------------
    def _choice(self, items: Iterable[Any]) -> Any:
        seq = list(items)
        return seq[self.random.randrange(len(seq))]

    def get_status(self) -> Dict[str, Any]:
        status = dict(self._state.status)
        status["run_id"] = self._state.run_id
        status["clock"] = datetime.utcnow().isoformat() + "Z"
        trace_id = f"mock-{self.random.randint(10000, 99999)}"
        self._state.trace_id = trace_id
        status["trace_id"] = trace_id
        status["paper"] = status.get("profile", "paper") == "paper"
        status.setdefault("halted", False)
        if self._state.params:
            status["strategy_params"] = self._state.params
        return status

    def start_paper(self, preset: Optional[str] = None) -> Dict[str, Any]:
        run_id = f"paper-{self.random.randint(1000, 9999)}"
        self._state.run_id = run_id
        self._state.status["profile"] = "paper"
        if preset is not None:
            self._state.status["preset"] = preset
        self._state.status["paper"] = True
        self._state.status["halted"] = False
        return {"run_id": run_id}

    def start_live(self, preset: Optional[str] = None) -> Dict[str, Any]:
        run_id = f"live-{self.random.randint(1000, 9999)}"
        self._state.run_id = run_id
        self._state.status["profile"] = "live"
        if preset is not None:
            self._state.status["preset"] = preset
        self._state.status["paper"] = False
        self._state.status["halted"] = False
        return {"run_id": run_id}

    def stop_all(self) -> Dict[str, Any]:
        self._state.run_id = None
        self._state.status["halted"] = False
        return {"ok": True}

    def flatten_and_halt(self) -> Dict[str, Any]:
        self._state.run_id = None
        self._state.status["halted"] = True
        return {"ok": True}

    def get_equity_curve(self, run_id: Optional[str] = None) -> List[EquityPoint]:
        payload = _load_json_fixture("equity_curve")
        return [EquityPoint(**item) for item in payload]

    def get_risk_snapshot(self) -> RiskSnapshot:
        payload = _load_json_fixture("risk_snapshot")
        payload["run_id"] = self._state.run_id
        return RiskSnapshot(**payload)

    def get_orders(self) -> List[Order]:
        payload = _load_json_fixture("orders")
        return [Order(**item) for item in payload]

    def get_positions(self) -> List[Position]:
        payload = _load_json_fixture("positions")
        return [Position(**item) for item in payload]

    def get_trades(self, filters: Optional[Dict[str, Any]] = None) -> List[Trade]:
        payload = _load_json_fixture("trades")
        trades = [Trade(**item) for item in payload]
        if not filters:
            return trades
        filtered = []
        for trade in trades:
            include = True
            for key, value in filters.items():
                if not value:
                    continue
                attr = getattr(trade, key, None)
                if attr is None:
                    continue
                if isinstance(attr, datetime):
                    if value not in trade.timestamp.isoformat():
                        include = False
                        break
                elif str(attr).lower() != str(value).lower():
                    include = False
                    break
            if include:
                filtered.append(trade)
        return filtered

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> OptionChain:
        name = f"option_chain_{symbol.lower()}"
        payload = _load_json_fixture(name)
        if expiry:
            payload["expiry"] = expiry
        chain = OptionChain(**payload)
        if expiry:
            chain.expiry = datetime.fromisoformat(expiry)
        return chain

    def get_greeks(self, contract: str) -> Greeks:
        payload = _load_json_fixture("greeks")
        payload["contract"] = contract
        return Greeks(**payload)

    def get_indicators(self, symbol: str, lookback: int) -> Indicators:
        payload = _load_json_fixture("indicators")
        payload["symbol"] = symbol
        payload["series"] = payload.get("series", [])[: lookback // 5 or 1]
        return Indicators(**payload)

    def apply_strategy_params(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._state.params.update(payload)
        return {"ok": True, "applied": payload}

    def get_backtest_runs(self) -> List[RunInfo]:
        payload = _load_json_fixture("backtest_runs")
        return [RunInfo(**item) for item in payload]

    def get_backtest_report(self, run_id: str) -> ReportSummary:
        payload = _load_json_fixture("backtest_report")
        payload["run_id"] = run_id
        payload["equity_curve"] = [EquityPoint(**item) for item in payload["equity_curve"]]
        return ReportSummary(**payload)

    def get_logs(self, tail: int, level: Optional[str] = None) -> List[LogEvent]:
        payload = _load_json_fixture("logs")
        events = [LogEvent(**item) for item in payload][-tail:]
        if level:
            return [event for event in events if event.level.lower() == level.lower()]
        return events

    def get_pacing_stats(self) -> PacingStats:
        payload = _load_json_fixture("pacing")
        return PacingStats(**payload)


def get_backend() -> BrokerAPI:
    """Return the proper backend implementation based on environment variables."""
    if mock_mode():
        return MockAPI()
    return RealAPI()
