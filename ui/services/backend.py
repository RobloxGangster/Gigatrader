"""Backend client abstractions for the Gigatrader UI."""

from __future__ import annotations

import json
import os
import random
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Protocol

from pydantic import BaseModel, Field
from requests import HTTPError
import streamlit as st

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
)

ENV_BACKEND_BASE = (
    os.getenv("BACKEND_BASE")
    or os.getenv("GT_API_BASE_URL")
    or "http://127.0.0.1:8000"
)
_FALLBACK_SESSION_STATE: Dict[str, Any] = {}


def _session_state() -> MutableMapping[str, Any]:
    try:
        return st.session_state
    except (RuntimeError, AttributeError):  # pragma: no cover - streamlit runtime guard
        return _FALLBACK_SESSION_STATE


def get_api_base() -> str:
    state = _session_state()
    value = state.get("backend_base")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ENV_BACKEND_BASE


def ensure_backend_base() -> None:
    state = _session_state()
    if "backend_base" not in state:
        state["backend_base"] = ENV_BACKEND_BASE
    else:
        current = state.get("backend_base")
        if not isinstance(current, str) or not current.strip():
            state["backend_base"] = ENV_BACKEND_BASE

from ui.utils.runtime import get_runtime_flags

_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"
_DEFAULT_TIMEOUT = 8

# --- Normalization helpers (keep near other helpers) ---


def _coerce_str(x) -> Optional[str]:
    if x is None:
        return None
    try:
        return str(x)
    except Exception:
        return None


def _coerce_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _coerce_int(x) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None


_STATUS_MAP = {
    # Alpaca → UI
    "new": "pending",
    "accepted": "pending",
    "pending_new": "pending",
    "accepted_for_bidding": "pending",
    "calculated": "pending",

    "partially_filled": "working",
    "pending_cancel": "working",
    "pending_replace": "working",
    "stopped": "working",
    "suspended": "working",

    "filled": "filled",

    "canceled": "cancelled",
    "expired": "cancelled",
    "replaced": "cancelled",
    "done_for_day": "cancelled",

    "rejected": "rejected",
}


def _map_status(raw_status: Optional[str]) -> Optional[str]:
    if not raw_status:
        return None
    return _STATUS_MAP.get(raw_status.lower(), raw_status.lower())


def _first(*keys_and_dicts) -> Any:
    """
    _first(('symbol', raw), ('asset_symbol', raw), ('asset', raw, 'symbol')) → returns first non-null
    Each arg is (key, dict) or (k1, dict, k2) for nested.
    """
    for item in keys_and_dicts:
        if len(item) == 2:
            k, d = item
            if isinstance(d, dict) and d.get(k) is not None:
                return d.get(k)
        elif len(item) == 3:
            k1, d, k2 = item
            if isinstance(d, dict) and isinstance(d.get(k1), dict):
                v = d[k1].get(k2)
                if v is not None:
                    return v
    return None


def _iso(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    try:
        # Accept common formats and return ISO8601
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat()
    except Exception:
        return _coerce_str(ts)


def _normalize_order_shape(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts Alpaca Trading v3 raw order or our internal shape and returns the UI Order schema.
    Required keys for UI model: order_id, client_order_id, symbol, side, tif, status, leaves_qty, created_at, updated_at
    """
    if not isinstance(raw, dict):
        return {}

    # IDs
    order_id = _coerce_str(_first(("order_id", raw), ("id", raw), ("client_order_id", raw)))
    client_order_id = _coerce_str(_first(("client_order_id", raw), ("clientOrderId", raw)))

    # Basics
    symbol = _coerce_str(_first(("symbol", raw), ("asset_symbol", raw), ("asset", raw, "symbol")))
    side = _coerce_str(_first(("side", raw), ("order_side", raw)))
    tif = _coerce_str(_first(("tif", raw), ("time_in_force", raw)))

    # Quantities
    qty = _coerce_float(_first(("qty", raw), ("quantity", raw), ("order_qty", raw)))
    filled_qty = _coerce_float(_first(("filled_qty", raw), ("filled_quantity", raw)))
    if qty is None and filled_qty is not None:
        qty = filled_qty  # minimal fallback
    leaves_qty = None
    if qty is not None and filled_qty is not None:
        leaves = qty - filled_qty
        leaves_qty = float(leaves if leaves > 0 else 0.0)

    # Pricing (optional)
    limit_price = _coerce_float(_first(("limit_price", raw), ("limit", raw)))
    stop_price = _coerce_float(_first(("stop_price", raw), ("stop", raw)))

    # Status + timestamps
    status_raw = _coerce_str(_first(("status", raw), ("order_status", raw)))
    status = _map_status(status_raw)

    created_at = _iso(_first(("created_at", raw), ("submitted_at", raw), ("timestamp", raw)))
    updated_at = _iso(
        _first(
            ("updated_at", raw),
            ("filled_at", raw),
            ("canceled_at", raw),
            ("failed_at", raw),
            ("replaced_at", raw),
        )
    ) or created_at

    # Compose normalized dict
    out: Dict[str, Any] = {
        "order_id": order_id,
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": side,
        "tif": tif,
        "qty": qty,
        "filled_qty": filled_qty,
        "leaves_qty": leaves_qty,
        "limit_price": limit_price,
        "stop_price": stop_price,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    return out


def _normalize_position_shape(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize positions coming from Alpaca or internal sources."""

    symbol = (
        raw.get("symbol")
        or raw.get("asset_symbol")
        or raw.get("asset", {}).get("symbol")
    )
    qty = _coerce_float(
        raw.get("qty")
        or raw.get("quantity")
        or raw.get("qty_available")
        or raw.get("exchange_qty")
        or raw.get("position_qty")
    )
    qty = qty if qty is not None else 0.0
    avg_price = _coerce_float(raw.get("avg_entry_price") or raw.get("avg_price"))
    avg_price = avg_price if avg_price is not None else 0.0
    market_price = _coerce_float(raw.get("current_price") or raw.get("market_price"))
    unrealized_pl = _coerce_float(
        raw.get("unrealized_pl")
        or raw.get("unrealized_plpc")
        or raw.get("unrealized_intraday_pl")
    )
    unrealized_pl = unrealized_pl if unrealized_pl is not None else 0.0
    side = "long" if qty >= 0 else "short"
    out = {
        "symbol": symbol,
        "qty": qty,
        "avg_price": avg_price,
        "market_price": market_price,
        "unrealized_pl": unrealized_pl,
        "side": side,
    }
    out.update({k: v for k, v in raw.items() if k not in out})
    return out


class BackendError(RuntimeError):
    """Raised when the backend cannot fulfil a request."""


class BrokerAPI(Protocol):
    """Protocol describing backend interactions required by the UI."""

    def broker_status(self) -> Dict[str, Any]: ...

    def get_status(self) -> Dict[str, Any]: ...

    def start_paper(self, preset: Optional[str] = None) -> Dict[str, Any]: ...

    def start_live(self, preset: Optional[str] = None) -> Dict[str, Any]: ...

    def stop_all(self) -> Dict[str, Any]: ...

    def flatten_and_halt(self) -> Dict[str, Any]: ...

    def get_equity_curve(self, run_id: Optional[str] = None) -> List[EquityPoint]: ...

    def get_risk_snapshot(self) -> RiskSnapshot: ...

    def get_orders(self) -> List[Order]: ...

    def get_positions(self) -> List[Position]: ...
    def get_account(self) -> Dict[str, Any]: ...

    def get_trades(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]: ...

    def options_chain(self, symbol: str, expiry: Optional[str] = None) -> Dict[str, Any]: ...

    def option_greeks(self, contract: str) -> Dict[str, Any]: ...

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> OptionChain: ...

    def get_greeks(self, contract: str) -> Greeks: ...

    def get_indicators(self, symbol: str, lookback: int) -> Indicators: ...

    def apply_strategy_params(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...

    def get_backtest_runs(self) -> List[RunInfo]: ...

    def get_backtest_report(self, run_id: str) -> ReportSummary: ...

    def get_logs(self, tail: int, level: Optional[str] = None) -> List[LogEvent]: ...

    def get_pacing_stats(self) -> PacingStats: ...
    def preview_signals(self, profile: str = "balanced", universe: Optional[List[str]] | None = None) -> Dict[str, Any]: ...
    def run_strategy_backtest(self, symbol: str, strategy: str, days: int) -> Dict[str, Any]: ...
    def get_ml_status(self) -> Dict[str, Any]: ...
    def get_ml_features(self, symbol: str) -> Dict[str, Any]: ...
    def ml_predict(self, symbol: str) -> Dict[str, Any]: ...
    def ml_train(self, symbols: Optional[List[str]] | None = None) -> Dict[str, Any]: ...
    def get_metrics(self) -> Dict[str, Any]: ...


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

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_client: Optional["ApiClient"] = None,
    ) -> None:
        base_candidate = base_url or get_api_base()
        if api_client is not None and base_url is None:
            self.client = api_client
        else:
            from ui.lib.api_client import ApiClient

            self.client = ApiClient(base=base_candidate, timeout=_DEFAULT_TIMEOUT)
        if self.client.timeout < _DEFAULT_TIMEOUT:
            self.client.timeout = _DEFAULT_TIMEOUT
        self.base_url = self.client.base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        default: Any = None,
    ) -> Any:
        clean_path = "/" + path.lstrip("/")
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            query = urllib.parse.urlencode(filtered, doseq=True)
            if query:
                clean_path = f"{clean_path}?{query}"

        request_kwargs: Dict[str, Any] = {"headers": _build_trace_headers()}
        if json_payload is not None:
            request_kwargs["json"] = json_payload

        try:
            response = self.client._request(method.upper(), clean_path, **request_kwargs)
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if method.upper() == "GET" and status in {404, 405}:
                return default if default is not None else {}
            raise BackendError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - defensive network guard
            raise BackendError(str(exc)) from exc
        parsed = self.client._parse_response(response)
        if isinstance(parsed, bytes):
            return parsed.decode("utf-8", "ignore")
        return parsed

    def broker_status(self) -> Dict[str, Any]:
        payload = self._request("GET", "/broker/status", default={})
        if isinstance(payload, Mapping):
            return dict(payload)
        raise BackendError("Invalid broker status response")

    def get_status(self) -> Dict[str, Any]:
        return self._request("GET", "/status", default={})

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
        payload = self._request(
            "GET",
            "/equity",
            params={"run_id": run_id} if run_id else None,
            default=[],
        )
        return [EquityPoint(**item) for item in payload]

    def get_risk_snapshot(self) -> RiskSnapshot:
        try:
            payload = self._request("GET", "/risk", default={})
        except Exception:
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                "profile": "balanced",
                "equity": 0.0,
                "cash": 0.0,
                "exposure_pct": 0.0,
                "day_pnl": 0.0,
                "leverage": 1.0,
                "kill_switch": False,
                "limits": {
                    "max_position_pct": 0.2,
                    "max_leverage": 2.0,
                    "max_daily_loss_pct": 0.05,
                },
                "timestamp": now,
            }
        # Backward-compat: older backends may not include these keys
        payload.setdefault("profile", "balanced")
        payload.setdefault("equity", 0.0)
        payload.setdefault("cash", 0.0)
        payload.setdefault("exposure_pct", 0.0)
        payload.setdefault("day_pnl", 0.0)
        payload.setdefault("leverage", 0.0)
        payload.setdefault("kill_switch", False)
        payload.setdefault(
            "limits",
            {
                "max_position_pct": 0.0,
                "max_leverage": 0.0,
                "max_daily_loss_pct": 0.0,
            },
        )
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        payload.setdefault("run_id", "idle")
        payload.setdefault("daily_loss_pct", 0.0)
        payload.setdefault("max_exposure", float(os.getenv("MAX_NOTIONAL", "0") or 0))
        payload.setdefault("open_positions", 0)
        # 'breached' tracks hard risk/kill — default to kill_switch if missing
        payload.setdefault("breached", bool(payload.get("kill_switch", False)))
        return RiskSnapshot(**payload)

    def get_orders(self) -> List[Order]:
        payload = self._request("GET", "/orders", params={"live": True}, default=[])
        normalized: List[Dict[str, Any]] = []
        for item in payload:
            rec = _normalize_order_shape(item)
            # Require a minimal set, else skip the row
            if not (rec.get("order_id") and rec.get("symbol") and rec.get("side")):
                continue
            # Ensure status & timestamps are populated
            rec["status"] = rec.get("status") or "pending"
            rec["created_at"] = rec.get("created_at") or datetime.utcnow().isoformat()
            rec["updated_at"] = (
                rec.get("updated_at")
                or rec["created_at"]
                or datetime.utcnow().isoformat()
            )
            rec["tif"] = rec.get("tif") or "day"
            rec["leaves_qty"] = (
                rec.get("leaves_qty")
                if rec.get("leaves_qty") is not None
                else (
                    max(
                        0.0,
                        float(rec.get("qty", 0) or 0)
                        - float(rec.get("filled_qty", 0) or 0),
                    )
                )
            )
            rec["qty"] = rec.get("qty") if rec.get("qty") is not None else float(rec.get("filled_qty", 0) or 0)
            rec["filled_qty"] = rec.get("filled_qty") if rec.get("filled_qty") is not None else 0.0
            normalized.append(rec)
        return [Order(**row) for row in normalized]

    def get_positions(self) -> List[Position]:
        payload = self._request("GET", "/positions", params={"live": True}, default=[])
        normalized = [_normalize_position_shape(item) for item in payload]
        return [Position(**item) for item in normalized]

    def get_account(self) -> Dict[str, Any]:
        return self._request("GET", "/alpaca/account", default={})

    def options_chain(self, symbol: str, expiry: Optional[str] = None) -> Dict[str, Any]:
        payload = self._request(
            "GET",
            "/options/chain",
            params={"symbol": symbol, "expiry": expiry},
            default={},
        )
        if isinstance(payload, Mapping):
            return dict(payload)
        raise BackendError("Invalid option chain payload")

    def option_greeks(self, contract: str) -> Dict[str, Any]:
        payload = self._request(
            "GET",
            "/options/greeks",
            params={"contract": contract},
            default={},
        )
        if isinstance(payload, Mapping):
            return dict(payload)
        raise BackendError("Invalid option greeks payload")

    def get_trades(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Return recent broker activity normalised for the Trade Blotter."""

        if filters is None:
            filters = {}

        try:
            payload = self._request("GET", "/telemetry/trades", default=[])
        except BackendError:
            payload = []

        if not isinstance(payload, list):
            return []

        symbol_filter = (filters.get("symbol") or "").strip().upper()
        sides_filter = {
            str(item).lower()
            for item in (filters.get("side") or [])
            if item
        }
        statuses_filter = {
            str(item).lower()
            for item in (filters.get("status") or [])
            if item
        }

        start = filters.get("start")
        end = filters.get("end")

        try:
            limit = int(filters.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50

        def _extract_ts(order: Mapping[str, Any]) -> Optional[str]:
            for key in ("ts", "filled_at", "submitted_at", "created_at", "updated_at"):
                value = order.get(key)
                if value:
                    return str(value)
            return None

        def keep(order: Dict[str, Any]) -> bool:
            sym_ok = True
            if symbol_filter:
                sym_ok = str(order.get("symbol", "")).upper() == symbol_filter

            side_ok = True
            if sides_filter:
                side_ok = str(order.get("side", "")).lower() in sides_filter

            status_ok = True
            if statuses_filter:
                status_ok = str(order.get("status", "")).lower() in statuses_filter

            time_ok = True
            ts_str = _extract_ts(order)
            if ts_str and (start or end):
                from dateutil import parser as date_parser

                try:
                    ts = date_parser.parse(ts_str)
                    if start:
                        try:
                            ts_start = date_parser.parse(str(start))
                            if ts < ts_start:
                                time_ok = False
                        except Exception:  # noqa: BLE001 - ignore bad filter values
                            pass
                    if end:
                        try:
                            ts_end = date_parser.parse(str(end))
                            if ts > ts_end:
                                time_ok = False
                        except Exception:  # noqa: BLE001 - ignore bad filter values
                            pass
                except Exception:  # noqa: BLE001 - ignore parse errors
                    pass

            return sym_ok and side_ok and status_ok and time_ok

        filtered = [order for order in payload if isinstance(order, dict) and keep(order)]
        if limit > 0:
            return filtered[:limit]
        return filtered

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> OptionChain:
        payload = self.options_chain(symbol, expiry)
        return OptionChain(**payload)

    def get_greeks(self, contract: str) -> Greeks:
        payload = self.option_greeks(contract)
        return Greeks(**payload)

    def get_indicators(self, symbol: str, lookback: int) -> Indicators:
        payload = self._request(
            "GET", "/indicators", params={"symbol": symbol, "lookback": lookback}
        )
        return Indicators(**payload)

    def apply_strategy_params(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/strategy/params", json_payload=payload)

    def get_backtest_runs(self) -> List[RunInfo]:
        payload = self._request("GET", "/backtests", default=[])
        return [RunInfo(**item) for item in payload]

    def get_backtest_report(self, run_id: str) -> ReportSummary:
        payload = self._request(
            "GET",
            "/backtests/report",
            params={"run_id": run_id},
            default={},
        )
        return ReportSummary(**payload)

    def get_logs(self, tail: int, level: Optional[str] = None) -> List[LogEvent]:
        payload = self._request(
            "GET", "/logs", params={"tail": tail, "level": level} if level else {"tail": tail}
        )
        return [LogEvent(**item) for item in payload]

    def get_pacing_stats(self) -> PacingStats:
        payload = self._request("GET", "/pacing", default={})
        return PacingStats(**payload)

    def preview_signals(self, profile: str = "balanced", universe: Optional[List[str]] | None = None) -> Dict[str, Any]:
        params = {"profile": profile}
        if universe:
            params["universe"] = ",".join(universe)
        return self._request("GET", "/signals/preview", params=params, default={})

    def run_strategy_backtest(self, symbol: str, strategy: str, days: int) -> Dict[str, Any]:
        payload = {"symbol": symbol, "strategy": strategy, "days": days}
        return self._request("POST", "/backtest/run", json_payload=payload)

    def get_ml_status(self) -> Dict[str, Any]:
        return self._request("GET", "/ml/status", default={})

    def get_ml_features(self, symbol: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/ml/features",
            params={"symbol": symbol},
            default={},
        )

    def ml_predict(self, symbol: str) -> Dict[str, Any]:
        return self._request("POST", "/ml/predict", params={"symbol": symbol})

    def ml_train(self, symbols: Optional[List[str]] | None = None) -> Dict[str, Any]:
        payload = {"symbols": symbols} if symbols else None
        return self._request("POST", "/ml/train", json_payload=payload)

    def get_metrics(self) -> Dict[str, Any]:
        payload = self._request("GET", "/telemetry/metrics", default={})
        if isinstance(payload, Mapping):
            return dict(payload)
        return {}


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

    def broker_status(self) -> Dict[str, Any]:
        profile = self._state.status.get("profile", "mock")
        dry_run = profile != "live"
        return {
            "ok": True,
            "broker": "mock",
            "impl": type(self).__name__,
            "dry_run": dry_run,
            "profile": profile,
        }

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
        payload["run_id"] = self._state.run_id or payload.get("run_id") or "idle"
        return RiskSnapshot(**payload)

    def get_orders(self) -> List[Order]:
        payload = _load_json_fixture("orders")
        normalized = [_normalize_order_shape(item) for item in payload]
        return [Order(**item) for item in normalized]

    def get_positions(self) -> List[Position]:
        payload = _load_json_fixture("positions")
        normalized = [_normalize_position_shape(item) for item in payload]
        return [Position(**item) for item in normalized]

    def get_account(self) -> Dict[str, Any]:
        snapshot = self.get_risk_snapshot()
        return {
            "mock_mode": True,
            "equity": snapshot.equity,
            "cash": snapshot.cash,
            "buying_power": snapshot.max_exposure,
            "portfolio_value": snapshot.equity,
        }

    def get_trades(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload = _load_json_fixture("trades")
        if not isinstance(payload, list):
            return []

        filters = filters or {}
        symbol_filter = (filters.get("symbol") or "").strip().upper()
        sides_filter = {
            str(item).lower()
            for item in (filters.get("side") or [])
            if item
        }
        statuses_filter = {
            str(item).lower()
            for item in (filters.get("status") or [])
            if item
        }

        start = filters.get("start")
        end = filters.get("end")

        def keep(order: Dict[str, Any]) -> bool:
            sym_ok = True
            if symbol_filter:
                sym_ok = str(order.get("symbol", "")).upper() == symbol_filter

            side_ok = True
            if sides_filter:
                side_ok = str(order.get("side", "")).lower() in sides_filter

            status_ok = True
            if statuses_filter:
                status_ok = str(order.get("status", "")).lower() in statuses_filter

            time_ok = True
            ts_str = order.get("filled_at") or order.get("submitted_at")
            if ts_str and (start or end):
                from dateutil import parser as date_parser

                try:
                    ts = date_parser.parse(ts_str)
                    if start:
                        try:
                            ts_start = date_parser.parse(str(start))
                            if ts < ts_start:
                                time_ok = False
                        except Exception:  # noqa: BLE001 - ignore bad filter values
                            pass
                    if end:
                        try:
                            ts_end = date_parser.parse(str(end))
                            if ts > ts_end:
                                time_ok = False
                        except Exception:  # noqa: BLE001 - ignore bad filter values
                            pass
                except Exception:  # noqa: BLE001 - ignore parse errors
                    pass

            return sym_ok and side_ok and status_ok and time_ok

        return [order for order in payload if isinstance(order, dict) and keep(order)]

    def preview_signals(self, profile: str = "balanced", universe: Optional[List[str]] | None = None) -> Dict[str, Any]:
        symbols = universe or ["AAPL", "MSFT"]
        now = datetime.utcnow().isoformat() + "Z"
        candidates = []
        for sym in symbols:
            base_price = 150 + self.random.random() * 5
            candidates.append({"kind": "equity", "symbol": sym, "side": "buy", "entry": base_price, "stop": base_price * 0.99, "target": base_price * 1.02, "confidence": round(1.0 + self.random.random() * 0.5, 3), "rationale": "Mock momentum setup", "meta": {"strategy": "intraday_momentum"}})
        return {"generated_at": now, "profile": profile, "candidates": candidates}

    def run_strategy_backtest(self, symbol: str, strategy: str, days: int) -> Dict[str, Any]:
        equity_curve = []
        pnl = 0.0
        for idx in range(10):
            pnl += self.random.uniform(-50, 80)
            equity_curve.append({"time": datetime.utcnow().isoformat() + "Z", "equity": pnl})
        stats = {"cagr": 0.12, "sharpe": 1.4, "max_dd": -0.05, "winrate": 0.55, "avg_r": 0.8, "avg_trade": pnl / 10, "exposure": 0.5, "return_pct": 0.1}
        return {"trades": [{"symbol": symbol, "side": "buy", "qty": 10, "pnl": pnl, "reason": strategy}], "equity_curve": equity_curve, "stats": stats}

    def get_ml_status(self) -> Dict[str, Any]:
        return {"model": "mock_model", "created_at": datetime.utcnow().isoformat() + "Z", "metrics": {"auc": 0.6, "accuracy": 0.55}}

    def get_ml_features(self, symbol: str) -> Dict[str, Any]:
        features = {f"feat_{i}": round(self.random.random(), 4) for i in range(5)}
        return {"symbol": symbol.upper(), "features": features, "meta": {"generated_at": datetime.utcnow().isoformat() + "Z"}}

    def ml_predict(self, symbol: str) -> Dict[str, Any]:
        return {"symbol": symbol.upper(), "p_up_15m": round(self.random.random(), 3), "model": "mock_model"}

    def ml_train(self, symbols: Optional[List[str]] | None = None) -> Dict[str, Any]:
        metrics = {sym: {"auc": 0.6, "accuracy": 0.55} for sym in (symbols or ["AAPL"])}
        return {"model": "mock_model", "metrics": metrics}

    def get_metrics(self) -> Dict[str, Any]:
        equity = 100000 + self.random.uniform(-500, 500)
        buying_power = 200000 + self.random.uniform(-1000, 1000)
        day_pl = self.random.uniform(-750, 750)
        positions = [
            {
                "symbol": "AAPL",
                "qty": 10.0,
                "avg_price": 150.0,
                "market_price": 151.5,
                "unrealized_pl": 15.0,
            },
            {
                "symbol": "MSFT",
                "qty": -5.0,
                "avg_price": 320.0,
                "market_price": 318.25,
                "unrealized_pl": 8.75,
            },
        ]
        now = datetime.utcnow().isoformat() + "Z"
        return {
            "equity": round(equity, 2),
            "buying_power": round(buying_power, 2),
            "day_pl": round(day_pl, 2),
            "positions": positions,
            "risk": {
                "kill_switch_engaged": False,
                "kill_switch_reason": None,
                "daily_loss_limit": 2000.0,
                "max_portfolio_notional": 100000.0,
                "max_positions": 10,
                "cooldown_active": False,
            },
            "orchestrator": {
                "state": "running",
                "last_error": None,
                "last_heartbeat": now,
                "can_trade": True,
                "trade_guard_reason": None,
                "kill_switch_engaged": False,
                "kill_switch_reason": None,
            },
        }

    def options_chain(self, symbol: str, expiry: Optional[str] = None) -> Dict[str, Any]:
        name = f"option_chain_{symbol.lower()}"
        payload = _load_json_fixture(name)
        if expiry:
            payload["expiry"] = expiry
        return dict(payload)

    def option_greeks(self, contract: str) -> Dict[str, Any]:
        payload = _load_json_fixture("greeks")
        payload["contract"] = contract
        return dict(payload)

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> OptionChain:
        payload = self.options_chain(symbol, expiry)
        chain = OptionChain(**payload)
        if expiry:
            chain.expiry = datetime.fromisoformat(expiry)
        return chain

    def get_greeks(self, contract: str) -> Greeks:
        payload = self.option_greeks(contract)
        return Greeks(**payload)

    def get_indicators(self, symbol: str, lookback: int) -> Indicators:
        payload = dict(_load_json_fixture("indicators"))
        payload["symbol"] = symbol
        payload.setdefault("interval", "1m")
        series_map = {
            name: list(values)
            for name, values in (payload.get("indicators") or {}).items()
            if isinstance(values, list)
        }

        if lookback > 0:
            for name, values in series_map.items():
                if values:
                    series_map[name] = values[-min(len(values), lookback) :]

        payload["indicators"] = series_map
        payload["has_data"] = bool(series_map)
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
    """Return the proper backend implementation based on runtime flags."""

    primary = RealAPI()
    flags = get_runtime_flags(primary)

    if flags.mock_mode:
        return MockAPI()

    if flags.base_url != primary.base_url:
        return RealAPI(base_url=flags.base_url)

    return primary
