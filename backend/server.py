# --- import bootstrap: ensure repo root first on sys.path ---
import sys, pathlib, os
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONPATH", str(ROOT))
# ------------------------------------------------------------

from dotenv import load_dotenv

# Load .env once on process start; don't override existing env
load_dotenv(override=False)


def _tail(x: str | None, n: int = 4) -> str | None:
    return x[-n:] if x else None


import asyncio
import copy
import json
import threading
import subprocess
import logging
import random
import time
from decimal import Decimal
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Tuple, Dict, Iterable, Literal, List, Callable

from fastapi import Body, FastAPI, Query, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import uvicorn

from app.data.market import build_data_client, bars_to_df
from app.signals.signal_engine import SignalEngine
from app.backtest.engine import run_trade_backtest
from app.ml.models import load_from_registry, DEFAULT_MODEL_NAME
from app.ml.trainer import latest_feature_row, train_intraday_classifier
from app.ml.features import FEATURE_LIST
from core.config import MOCK_MODE, TradeLoopConfig, get_signal_defaults, get_audit_config
from core.runtime_flags import get_runtime_flags
from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaOrderError, AlpacaUnauthorized

from app.execution.router import ExecIntent, OrderRouter
from app.risk import RiskManager
from app.state import ExecutionState
from core.config import alpaca_config_ok
from core.kill_switch import KillSwitch
from services.safety import breakers
from backend.pacing import load_pacing_snapshot
from app.trade.orchestrator import TradeOrchestrator
from app.execution.audit import AuditLog
from app.execution.reconcile import Reconciler
from app.oms.store import OmsStore
from app.data.quality import next_regular_close_cancel_time

_TEST_ORDERS_DEFAULT_DRY_RUN = os.getenv("TEST_ORDERS_DEFAULT_DRY_RUN", "true").lower() not in (
    "false",
    "0",
    "no",
    "off",
)

_kill_switch = KillSwitch()

_SENT_CACHE: Dict[Tuple[str, int, int], Tuple[float, Dict[str, Any]]] = {}
_SENT_TTL_SEC = 300  # 5 minutes

_FALSEY = {"false", "0", "no", "off"}


class OmsMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = defaultdict(float)
        self._states: Dict[str, float] = defaultdict(float)
        self._flags: Dict[str, float] = {}

    def increment(self, key: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[key] += value

    def note_state(self, state: str) -> None:
        with self._lock:
            self._states[state] += 1.0

    def set_flag(self, key: str, value: float) -> None:
        with self._lock:
            self._flags[key] = float(value)

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "states": dict(self._states),
                "flags": dict(self._flags),
            }


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if hasattr(value, "__float__"):
        try:
            return float(value)
        except Exception:  # pragma: no cover - defensive
            return None
    return None

# ---------- Robust runner import ----------
import importlib.util
def _import_runner():
    """
    Load app.cli:run even if a top-level module named 'app' shadows the package.
    """
    # If 'app' is a module (file), drop it so we can import the package namespace
    if "app" in sys.modules and not hasattr(sys.modules["app"], "__path__"):
        del sys.modules["app"]

    # Try normal package import
    try:
        from app.cli import run as run_cli
        return run_cli
    except Exception:
        pass

    # Fallback to direct file import
    cand = ROOT / "app" / "cli.py"
    if cand.exists():
        spec = importlib.util.spec_from_file_location("gt_runner.cli", cand)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        if hasattr(mod, "run"):
            return getattr(mod, "run")

    # Last-resort: scan for app/cli.py anywhere under repo
    for p in ROOT.rglob("cli.py"):
        if p.parent.name == "app":
            spec = importlib.util.spec_from_file_location("gt_runner.cli", p)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(mod)
            if hasattr(mod, "run"):
                return getattr(mod, "run")

    raise ImportError("Could not locate app.cli:run")

# ---------- Runner plumbing ----------
runner_task = None
runner_loop = None
runner_last_error: Optional[str] = None

class StartResp(BaseModel):
    run_id: str

class StatusResp(BaseModel):
    profile: str
    mode: str
    market_open: bool
    preset: Optional[str] = None
    last_error: Optional[str] = None

class RiskLimits(BaseModel):
    max_position_pct: float = 0.2
    max_leverage: float = 2.0
    max_daily_loss_pct: float = 0.05


class RiskSnapshot(BaseModel):
    # UI-required top-level fields
    run_id: str
    daily_loss_pct: float            # fraction of equity lost today [0..1]
    max_exposure: float              # portfolio notional cap (e.g., MAX_NOTIONAL)
    open_positions: int
    breached: bool                   # true if any hard risk breach or kill switch

    # Existing/aux fields
    profile: str
    equity: float
    cash: float
    exposure_pct: float
    day_pnl: float
    leverage: float
    kill_switch: bool
    limits: RiskLimits
    timestamp: str

class BacktestRequest(BaseModel):
    symbol: str
    strategy: Literal["intraday_momo", "intraday_revert", "swing_breakout"]
    days: int = 30


class TrainRequest(BaseModel):
    symbols: list[str] | None = None

class TradeStartOptions(BaseModel):
    profile: str | None = None
    universe: list[str] | None = None
    interval_sec: float | None = None
    top_n: int | None = None
    min_conf: float | None = None
    min_ev: float | None = None


class TestOrderRequest(BaseModel):
    """Flexible input for /orders/test (JSON or query)."""

    symbol: str
    side: Literal["buy", "sell"]
    qty: int
    limit_price: Optional[float] = None

log = logging.getLogger("backend")

try:
    _data_client = build_data_client(mock_mode=MOCK_MODE)
except Exception as exc:
    logging.getLogger("backend").info("data client fallback: %s", exc)
    _data_client = build_data_client(mock_mode=True)

_signal_engine = SignalEngine(_data_client, config=get_signal_defaults())

_execution_state = ExecutionState()


_broker = AlpacaAdapter()
if not _broker.is_configured():
    log.warning("alpaca adapter unavailable: credentials missing; broker calls disabled")

_risk_manager = RiskManager(_execution_state, kill_switch=_kill_switch)

def _resolve_path(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


class LiveBrokerFacade:
    def __init__(self, adapter: AlpacaAdapter) -> None:
        self.adapter = adapter

    def list_orders(self, status: str = "all") -> List[Any]:
        if not self.adapter.is_configured():
            raise AlpacaUnauthorized("not configured")
        client = self.adapter._ensure_client()
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        scopes = []
        if status == "all":
            scopes = [QueryOrderStatus.OPEN, QueryOrderStatus.CLOSED]
        elif status == "open":
            scopes = [QueryOrderStatus.OPEN]
        elif status == "closed":
            scopes = [QueryOrderStatus.CLOSED]
        else:
            raise ValueError(f"invalid status scope: {status}")

        orders: List[Any] = []
        for scope in scopes:
            req = GetOrdersRequest(status=scope)
            result = client.get_orders(req)
            if result:
                orders.extend(result)
        return orders

    def list_positions(self) -> List[Any]:
        if not self.adapter.is_configured():
            raise AlpacaUnauthorized("not configured")
        client = self.adapter._ensure_client()
        return list(client.get_all_positions())

    def cancel_all(self) -> Dict[str, Any]:
        return self.adapter.cancel_all()


class InMemoryMockBroker:
    def __init__(self) -> None:
        self._orders: List[Dict[str, Any]] = [copy.deepcopy(o) for o in Reconciler.mock_sample_orders()]
        self._positions: List[Dict[str, Any]] = [
            {
                "symbol": "AAPL",
                "qty": 10.0,
                "avg_entry": 145.0,
                "market_price": 150.0,
                "unrealized_pl": 50.0,
                "last_updated": None,
            },
            {
                "symbol": "MSFT",
                "qty": -5.0,
                "avg_entry": 325.0,
                "market_price": 320.0,
                "unrealized_pl": 25.0,
                "last_updated": None,
            },
        ]

    def list_orders(self, status: str = "all") -> List[Dict[str, Any]]:
        open_statuses = {"new", "accepted", "partially_filled"}
        closed_statuses = {"filled", "canceled", "rejected", "expired", "replaced"}
        filtered: List[Dict[str, Any]] = []
        for order in self._orders:
            status_value = order.get("status", "")
            if status == "open" and status_value not in open_statuses:
                continue
            if status == "closed" and status_value not in closed_statuses:
                continue
            filtered.append(copy.deepcopy(order))
        if status == "all":
            return [copy.deepcopy(o) for o in self._orders]
        return filtered

    def list_positions(self) -> List[Dict[str, Any]]:
        return [copy.deepcopy(p) for p in self._positions]

    def cancel_all(self) -> Dict[str, int]:
        open_statuses = {"new", "accepted", "partially_filled"}
        canceled = 0
        now = datetime.now(timezone.utc).isoformat()
        for order in self._orders:
            if order.get("status") in open_statuses:
                order["status"] = "canceled"
                order["updated_at"] = now
                canceled += 1
        return {"canceled": canceled, "failed": 0}


_audit_config = get_audit_config()
_audit_dir = _resolve_path(_audit_config.audit_dir)
_audit_dir.mkdir(parents=True, exist_ok=True)
_audit_log = AuditLog(_audit_dir / _audit_config.audit_file)
_reconcile_state_path = _audit_dir / _audit_config.reconcile_state_file

AUDIT_PATH = _audit_log.path

OMS_DB_PATH = Path(os.getenv("OMS_DB_PATH", "runtime/oms.db"))
OMS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
USE_WEBSOCKET = os.getenv("USE_WEBSOCKET", "true").lower() not in _FALSEY
CANCEL_AT_CLOSE = os.getenv("CANCEL_AT_CLOSE", "false").lower() not in _FALSEY

_oms_store = OmsStore(OMS_DB_PATH)
_oms_metrics = OmsMetrics()

_use_mock_broker = MOCK_MODE or not _broker.is_configured()
if _use_mock_broker:
    _reconcile_broker = InMemoryMockBroker()
else:
    _reconcile_broker = LiveBrokerFacade(_broker)

_order_router = OrderRouter(
    _risk_manager,
    _execution_state,
    store=_oms_store,
    audit=_audit_log,
    metrics=_oms_metrics,
    mock_mode=_use_mock_broker,
)
_trade_orchestrator = TradeOrchestrator(
    data_client=_data_client,
    signal_generator=_signal_engine,
    ml_predictor=None,
    risk_manager=_risk_manager,
    router=_order_router,
    config=TradeLoopConfig(),
)


def _update_oms_state(
    client_order_id: str,
    state: str,
    *,
    broker_order_id: str | None = None,
    filled_qty: float | None = None,
    raw: Dict[str, Any] | None = None,
    extras: Dict[str, Any] | None = None,
    source: str = "reconcile",
) -> None:
    previous = _oms_store.get_order_by_coid(client_order_id)
    prev_state = previous.get("state") if previous else None
    details: Dict[str, Any] = {
        "client_order_id": client_order_id,
        "state": state,
        "source": source,
    }
    if extras:
        details.update(extras)
    if broker_order_id:
        details["broker_order_id"] = broker_order_id
    if filled_qty is not None:
        details["filled_qty"] = filled_qty

    _oms_store.update_order_state(
        client_order_id,
        state=state,
        broker_order_id=broker_order_id,
        filled_qty=filled_qty,
        raw=raw,
        extra=extras,
    )

    log_change = prev_state != state or source != "reconcile"
    if log_change:
        _oms_store.append_journal(category=source, message=state, details=details)
        _audit_log.append({**details, "ts": datetime.now(timezone.utc).isoformat()})

    if prev_state != state:
        _oms_metrics.note_state(state)
        if state == "filled":
            _oms_metrics.increment("oms_fills_total")
        elif state == "rejected":
            _oms_metrics.increment("oms_rejects_total")
        elif state == "canceled":
            _oms_metrics.increment("oms_cancels_total")


_reconciler = Reconciler(
    broker=_reconcile_broker,
    audit=_audit_log,
    state_store_path=_reconcile_state_path,
    mock_mode=_use_mock_broker,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.execution = _execution_state
    app.state.state = _execution_state
    app.state.risk = _risk_manager
    app.state.broker = _broker
    app.state.trade_orchestrator = _trade_orchestrator
    app.state.audit_log = _audit_log
    app.state.reconciler = _reconciler
    app.state.reconcile_broker = _reconcile_broker
    app.state.oms_store = _oms_store
    app.state.oms_metrics = _oms_metrics
    app.state.alpaca_stream_connected = False

    _oms_metrics.set_flag("alpaca_stream_connected", 0.0)

    if _broker.is_configured() and not _use_mock_broker:
        try:
            _broker.fetch_and_merge_orders(_oms_store)
        except AlpacaUnauthorized:
            log.warning("startup reconcile skipped: alpaca unauthorized")
        except AlpacaOrderError as exc:
            log.warning("startup reconcile failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("startup reconcile error: %s", exc)

    stop_flag = False
    stream_stop = asyncio.Event()

    async def recon_loop() -> None:
        nonlocal stop_flag
        broker = _broker
        backoff_schedule = [2.0, 3.0, 5.0, 8.0, 10.0]
        backoff_index = 0
        auth_logged = False
        while not stop_flag:
            delay = backoff_schedule[min(backoff_index, len(backoff_schedule) - 1)]
            try:
                orders = broker.fetch_orders()
                positions = broker.fetch_positions()
                account = broker.fetch_account()
            except AlpacaUnauthorized:
                if not auth_logged:
                    log.warning(
                        "reconcile paused: alpaca unauthorized. retrying in %.0fs",
                        delay,
                    )
                    auth_logged = True
                backoff_index = min(backoff_index + 1, len(backoff_schedule) - 1)
                await asyncio.sleep(delay + random.uniform(0, 1.0))
                continue
            except AlpacaOrderError as exc:
                log.warning("reconcile broker error: %s", exc)
                backoff_index = min(backoff_index + 1, len(backoff_schedule) - 1)
                await asyncio.sleep(delay + random.uniform(0, 1.0))
                continue
            except Exception as exc:  # noqa: BLE001
                log.error("reconcile error (%s): %s", exc.__class__.__name__, exc)
                backoff_index = min(backoff_index + 1, len(backoff_schedule) - 1)
                await asyncio.sleep(delay + random.uniform(0, 1.0))
                continue

            auth_logged = False
            for order in orders:
                cid = str(order.get("client_order_id") or "").strip()
                if not cid:
                    continue
                state = AlpacaAdapter.map_order_state(order.get("status"))
                extras = {
                    "symbol": order.get("symbol"),
                    "side": order.get("side"),
                    "qty": _to_float(order.get("qty")),
                }
                broker_order_id = str(order.get("id") or "") or None
                filled_qty = _to_float(order.get("filled_qty"))
                _update_oms_state(
                    cid,
                    state,
                    broker_order_id=broker_order_id,
                    filled_qty=filled_qty,
                    raw=order,
                    extras=extras,
                    source="reconcile",
                )
            _oms_store.replace_positions(positions)
            _execution_state.update_orders(orders)
            _execution_state.update_positions(positions)
            _execution_state.update_account(account)
            _oms_metrics.increment("oms_reconcile_runs_total")
            backoff_index = 0
            await asyncio.sleep(backoff_schedule[0])

    async def handle_stream_update(payload: Dict[str, Any]) -> None:
        cid = str(payload.get("client_order_id") or "").strip()
        if not cid:
            return
        order_info = payload.get("order")
        if not isinstance(order_info, dict):
            order_info = None
        state = payload.get("state") or (
            AlpacaAdapter.map_order_state(order_info.get("status")) if order_info else "new"
        )
        broker_order_id = payload.get("broker_order_id")
        if broker_order_id is None and order_info:
            broker_order_id = order_info.get("id")
        filled_qty = _to_float(payload.get("filled_qty"))
        if filled_qty is None and order_info:
            filled_qty = _to_float(order_info.get("filled_qty"))
        extras = {
            "event": payload.get("event"),
            "symbol": order_info.get("symbol") if order_info else None,
            "side": order_info.get("side") if order_info else None,
        }
        extras = {k: v for k, v in extras.items() if v is not None}
        _update_oms_state(
            cid,
            state,
            broker_order_id=str(broker_order_id) if broker_order_id else None,
            filled_qty=filled_qty,
            raw=order_info or payload,
            extras=extras,
            source="stream",
        )
        execution = payload.get("execution")
        if isinstance(execution, dict):
            qty = _to_float(execution.get("qty"))
            price = _to_float(execution.get("price"))
            ts = execution.get("timestamp")
            if ts and hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            elif ts is not None:
                ts = str(ts)
            if qty or price:
                _oms_store.append_execution(
                    cid,
                    event_type=str(payload.get("event") or state),
                    fill_qty=qty,
                    fill_price=price,
                    event_ts=ts,
                    raw=execution,
                )

    async def stream_loop() -> None:
        nonlocal stop_flag
        if not USE_WEBSOCKET or _use_mock_broker or not _broker.is_configured():
            _oms_metrics.set_flag("alpaca_stream_connected", 0.0)
            return
        backoff = 2.0
        auth_logged = False
        while not stop_flag:
            try:
                stream_stop.clear()
                app.state.alpaca_stream_connected = True
                _oms_metrics.set_flag("alpaca_stream_connected", 1.0)
                await _broker.start_stream(handle_stream_update, stream_stop)
                app.state.alpaca_stream_connected = False
                _oms_metrics.set_flag("alpaca_stream_connected", 0.0)
                backoff = 2.0
            except AlpacaUnauthorized:
                app.state.alpaca_stream_connected = False
                _oms_metrics.set_flag("alpaca_stream_connected", 0.0)
                if not auth_logged:
                    log.warning("alpaca stream unauthorized; backing off")
                    auth_logged = True
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 60.0)
            except Exception as exc:  # noqa: BLE001
                app.state.alpaca_stream_connected = False
                _oms_metrics.set_flag("alpaca_stream_connected", 0.0)
                log.warning("alpaca stream error: %s", exc)
                await asyncio.sleep(backoff + random.uniform(0, backoff))
                backoff = min(backoff * 1.5, 60.0)

    async def _cancel_day_orders() -> None:
        orders = _oms_store.get_open_orders()
        for order in orders:
            tif = str(order.get("tif") or "").lower()
            if tif != "day":
                continue
            cid = str(order.get("client_order_id") or "").strip()
            if not cid:
                continue
            broker_order_id = order.get("broker_order_id")
            if _use_mock_broker or not _broker.is_configured():
                _update_oms_state(
                    cid,
                    "canceled",
                    broker_order_id=str(broker_order_id) if broker_order_id else None,
                    extras={"reason": "cancel_at_close"},
                    source="cancel_at_close",
                )
                continue
            if not broker_order_id:
                continue
            try:
                await asyncio.to_thread(_broker.cancel_order, str(broker_order_id))
            except AlpacaUnauthorized:
                log.warning("cancel_at_close unauthorized; aborting")
                break
            except AlpacaOrderError as exc:
                log.warning("cancel_at_close broker error: %s", exc)
            else:
                _update_oms_state(
                    cid,
                    "canceled",
                    broker_order_id=str(broker_order_id),
                    extras={"reason": "cancel_at_close"},
                    source="cancel_at_close",
                )

    async def cancel_loop() -> None:
        nonlocal stop_flag
        while not stop_flag:
            now = datetime.now(timezone.utc)
            target = next_regular_close_cancel_time(now)
            wait_seconds = max((target - now).total_seconds(), 60.0)
            while wait_seconds > 0 and not stop_flag:
                await asyncio.sleep(min(wait_seconds, 300.0))
                now = datetime.now(timezone.utc)
                wait_seconds = (target - now).total_seconds()
            if stop_flag:
                break
            try:
                await _cancel_day_orders()
            except Exception as exc:  # noqa: BLE001
                log.warning("cancel_at_close error: %s", exc)
            await asyncio.sleep(30)

    async def breaker_loop() -> None:
        nonlocal stop_flag
        if not breakers.is_enabled():
            return
        interval = max(0.1, breakers.check_interval_seconds())
        last_logged: set[str] = set()
        while not stop_flag:
            now = datetime.now(timezone.utc)
            trips = breakers.enforce_breakers(now, _kill_switch)
            trip_set = set(trips)
            if trip_set:
                if trip_set != last_logged or not _kill_switch_on():
                    log.error(
                        "safety breakers tripped: %s",
                        ", ".join(sorted(trip_set)),
                    )
                last_logged = trip_set
            else:
                if last_logged:
                    log.info("safety breakers cleared")
                last_logged = set()
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    recon_task = asyncio.create_task(recon_loop())
    stream_task = (
        asyncio.create_task(stream_loop())
        if USE_WEBSOCKET and not _use_mock_broker and _broker.is_configured()
        else None
    )
    cancel_task = asyncio.create_task(cancel_loop()) if CANCEL_AT_CLOSE else None
    breaker_task = asyncio.create_task(breaker_loop()) if breakers.is_enabled() else None

    try:
        yield
    finally:
        stop_flag = True
        stream_stop.set()
        for task in (recon_task, stream_task, cancel_task, breaker_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except Exception:
                pass


app = FastAPI(lifespan=lifespan)

from backend.routes import backtests_compat  # noqa: E402
from backend.routes import options as options_routes  # noqa: E402
from backend.routes import logs as logs_routes  # noqa: E402
from backend.routes import backtest_v2 as backtest_v2_routes  # noqa: E402
from backend.routes import ml as ml_routes  # noqa: E402
from backend.routes import metrics_extended as metrics_routes  # noqa: E402
from backend.routes import alpaca_live as alpaca_live_routes  # noqa: E402

app.include_router(ml_routes.router)
app.include_router(metrics_routes.router)
app.include_router(backtest_v2_routes.router)
app.include_router(backtests_compat.router)
app.include_router(options_routes.router)
app.include_router(logs_routes.router)
app.include_router(alpaca_live_routes.router)

def start_background_runner(profile: str = "paper"):
    global runner_task, runner_loop, runner_last_error
    runner_last_error = None
    if runner_task and not runner_task.done():
        return

    def _run():
        global runner_loop, runner_task, runner_last_error
        runner_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(runner_loop)
        try:
            run_cli = _import_runner()
        except Exception as e:
            runner_last_error = f"runner import failed: {e}"
            return
        try:
            runner_task = runner_loop.create_task(run_cli(async_mode=True, profile=profile))
            runner_loop.run_until_complete(runner_task)
        except Exception as e:
            runner_last_error = f"runner crashed: {e}"

    threading.Thread(target=_run, daemon=True).start()

# ---------- Health & status ----------
@app.get("/health")
def health():
    flags = get_runtime_flags()
    breaker_info = breakers.breaker_state()
    kill = _kill_switch_on()
    orchestrator_status = _trade_orchestrator.status()
    broker_status = {
        "source": "mock" if flags.mock_mode else "alpaca",
        "paper": flags.paper_trading,
    }
    stream_status = {"status": "unknown"}
    ok = not kill and not breaker_info.get("current")
    return {
        "ok": bool(ok),
        "mode": {"mock_mode": flags.mock_mode, "paper": flags.paper_trading},
        "orchestrator": orchestrator_status,
        "stream": stream_status,
        "broker": broker_status,
        "kill_switch": kill,
        "breakers": breaker_info,
    }

@app.get("/status", response_model=StatusResp)
def status():
    return StatusResp(
        profile="live" if os.environ.get("LIVE_TRADING", "false").lower() == "true" else "paper",
        mode="running" if runner_task and not runner_task.done() else "stopped",
        market_open=False,
        preset=os.environ.get("RISK_PROFILE", "balanced"),
        last_error=runner_last_error,
    )


@app.post("/trade/start")
async def trade_start(request: Request, options: TradeStartOptions | None = None):
    overrides = _parse_trade_overrides(request, options)
    if _trade_orchestrator.ml_predictor is None:
        try:
            _trade_orchestrator.ml_predictor = load_from_registry()
        except Exception:
            _trade_orchestrator.ml_predictor = None
    config = await _trade_orchestrator.start(overrides)
    snapshot = _trade_orchestrator.status()
    return {
        "status": "running" if snapshot.get("running") else "starting",
        "config": config.to_dict(),
        "broker": snapshot.get("broker", {}),
        "metrics": snapshot.get("metrics", {}),
    }


@app.post("/trade/stop")
async def trade_stop():
    await _trade_orchestrator.stop()
    snapshot = _trade_orchestrator.status()
    return {"status": "stopped", "running": snapshot.get("running")}


@app.get("/trade/status")
def trade_status():
    return _trade_orchestrator.status()


@app.get("/trade/debug/last_decisions")
def trade_last_decisions():
    return {"decisions": _trade_orchestrator.last_decisions()}


@app.get("/trade/debug/config")
def trade_debug_config():
    return _trade_orchestrator.resolved_config()


def _kill_switch_on() -> bool:
    try:
        return _kill_switch.engaged_sync()
    except Exception:
        return os.path.exists(".kill_switch")


def _read_run_id() -> str:
    """Try to read current run id from a file set by paper runner; else 'idle'."""
    p = Path(".run_id")
    if p.exists():
        try:
            s = p.read_text(encoding="utf-8").strip()
            if s:
                return s
        except Exception:
            pass
    return "idle"

def _normalize_payload(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _normalize_payload(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_payload(v) for v in obj]
    return obj



def _parse_trade_overrides(request: Request, payload: TradeStartOptions | None) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if payload is not None:
        overrides.update(payload.model_dump(exclude_none=True))

    params = request.query_params

    def _assign(name: str, caster) -> None:
        value = params.get(name)
        if value is None or value == "":
            return
        try:
            overrides[name] = caster(value)
        except (TypeError, ValueError):
            pass

    if "profile" in params:
        overrides["profile"] = params.get("profile")

    universe_raw = params.get("universe")
    if universe_raw:
        symbols = [sym.strip().upper() for sym in universe_raw.split(",") if sym.strip()]
        if symbols:
            overrides["universe"] = symbols

    _assign("interval_sec", float)
    _assign("min_conf", float)
    _assign("min_ev", float)
    _assign("top_n", int)

    return overrides





def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name)
        return float(v) if v not in (None, "", "None") else default
    except Exception:
        return default


@app.get("/risk", response_model=RiskSnapshot)
def get_risk():
    """
    Return current risk snapshot from Alpaca (if keys present) + local settings.
    Always returns 200 with safe defaults so the UI can render.
    """
    profile = os.environ.get("RISK_PROFILE", "balanced")
    limits = RiskLimits(
        max_position_pct=_env_float("RISK_MAX_POSITION_PCT", 0.2),
        max_leverage=_env_float("RISK_MAX_LEVERAGE", 2.0),
        max_daily_loss_pct=_env_float("RISK_MAX_DAILY_LOSS_PCT", 0.05),
    )

    snapshot = _execution_state.account_snapshot()
    if not snapshot.get("id") and alpaca_config_ok():
        try:
            account = _broker.fetch_account()
            _execution_state.update_account(account)
            snapshot = _execution_state.account_snapshot()
        except (AlpacaUnauthorized, AlpacaOrderError) as exc:
            log.warning("risk account fetch failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("risk account fetch failed: %s", exc)

    equity = float(snapshot.get("equity", 0.0) or 0.0)
    cash = float(snapshot.get("cash", 0.0) or 0.0)
    day_pnl = float(snapshot.get("day_pnl", 0.0) or 0.0)
    leverage = float(snapshot.get("multiplier", 1.0) or 1.0)
    portfolio_notional = float(_execution_state.get_portfolio_notional())
    open_positions = sum(1 for pos in _execution_state.get_positions().values() if abs(pos.qty) > 0)

    # Derived & limits from env
    daily_loss_limit_abs = _env_float("DAILY_LOSS_LIMIT", -1.0)   # absolute currency amount
    max_notional = _env_float("MAX_NOTIONAL", -1.0)

    # daily loss percent (treat gains as 0% loss)
    loss_abs = max(0.0, -float(day_pnl))
    daily_loss_pct = 0.0 if equity <= 0 else (loss_abs / max(equity, 1e-9))

    # max exposure defaults: if not set, approximate from equity * leverage
    if max_notional <= 0:
        max_exposure = (equity * max(leverage, 1.0)) or 0.0
    else:
        max_exposure = max_notional

    # breach logic: kill switch OR (configured daily loss limit exceeded)
    limit_breached = False
    if daily_loss_limit_abs is not None and daily_loss_limit_abs > 0:
        limit_breached = (loss_abs >= daily_loss_limit_abs)

    kill = _kill_switch_on()
    breached = bool(kill or limit_breached)

    return RiskSnapshot(
        run_id=_read_run_id(),
        daily_loss_pct=float(daily_loss_pct),
        max_exposure=float(max_exposure),
        open_positions=int(open_positions),
        breached=breached,

        profile=profile,
        equity=float(equity),
        cash=float(cash),
        exposure_pct=0.0 if equity <= 0 else min(1.0, portfolio_notional / max(equity, 1e-9)),
        day_pnl=float(day_pnl),
        leverage=float(leverage),
        kill_switch=kill,
        limits=limits,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
@app.get("/debug/alpaca")
def debug_alpaca():
    env_key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID")
    env_secret = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    env_base = os.getenv("APCA_API_BASE_URL") or os.getenv("ALPACA_API_BASE_URL")

    try:
        info = _broker.debug_info() if _broker else {}
    except Exception as exc:  # noqa: BLE001
        log.debug("alpaca debug info failed: %s", exc)
        info = {}

    if not isinstance(info, dict):
        info = {}

    info.setdefault("configured", bool(_broker and _broker.is_configured()))
    if env_base and "base_url" not in info:
        info["base_url"] = env_base
    if env_base and "paper" not in info:
        info["paper"] = "paper" in env_base.lower()

    info["env_key_tail"] = _tail(env_key)
    info["env_secret_set"] = bool(env_secret)
    if env_base:
        info["env_base_url"] = env_base

    return info


@app.get("/alpaca/ping")
def alpaca_ping():
    if not _broker.is_configured():
        return {"auth_ok": False, "error": "alpaca_not_configured"}
    try:
        acct = _broker.fetch_account()
        return {
            "auth_ok": True,
            "status": acct.get("status"),
            "cash": acct.get("cash"),
        }
    except AlpacaUnauthorized:
        return {"auth_ok": False, "error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"auth_ok": False, "error": f"alpaca_error:{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"auth_ok": False, "error": str(exc)}


@app.get("/alpaca/account")
def alpaca_account():
    if not _broker.is_configured():
        return {"error": "Alpaca client not configured"}
    try:
        acct = _broker.fetch_account()
    except AlpacaUnauthorized:
        return {"error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"error": f"alpaca_error:{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {
        "equity": acct.get("equity"),
        "cash": acct.get("cash"),
        "buying_power": acct.get("buying_power"),
        "pattern_day_trader": acct.get("pattern_day_trader"),
        "daytrade_count": acct.get("daytrade_count"),
    }


@app.post("/alpaca/close_all_positions")
def alpaca_close_all_positions():
    if not _broker.is_configured():
        return {"ok": False, "error": "alpaca_not_configured"}
    try:
        _broker.close_all_positions(cancel_orders=True)
        return {"ok": True}
    except AlpacaUnauthorized:
        return {"ok": False, "error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"ok": False, "error": f"alpaca_error:{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@app.post(
    "/orders/test",
    summary="Place a tiny test order via JSON body or query params",
    description=(
        "Accepts either a JSON body: "
        '{"symbol":"AAPL","side":"buy","qty":1,"limit_price":1.00} '
        "or traditional query params ?symbol=AAPL&side=buy&qty=1&limit_price=1.00"
    ),
)
def orders_test(
    symbol: Optional[str] = Query(None),
    side: Optional[Literal["buy", "sell"]] = Query(None),
    qty: Optional[int] = Query(None),
    limit_price: Optional[float] = Query(None),
    body: Optional[TestOrderRequest] = Body(None),
    confirm: bool = Query(default=False),
    execute: bool | None = Query(default=None, alias="execute"),
):
    """Submit a sample order; generates a fresh ``client_order_id`` on every call."""

    if execute is not None:
        confirm = execute

    if body is not None:
        data = body.model_dump()
    else:
        data = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "limit_price": limit_price,
        }

    missing = [key for key in ("symbol", "side", "qty") if data.get(key) is None]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "Missing required field(s): "
                + ", ".join(missing)
                + ". Provide in JSON body or query parameters."
            ),
        )

    _symbol = str(data["symbol"])
    _side = str(data["side"])
    _qty = int(data["qty"])
    _limit = (
        float(data["limit_price"]) if data.get("limit_price") is not None else None
    )

    dry_run = (not confirm) if _TEST_ORDERS_DEFAULT_DRY_RUN else False

    if not _broker.is_configured():
        return {
            "accepted": False,
            "reason": "broker_error:Alpaca client not configured",
            "client_order_id": None,
        }

    try:
        intent = ExecIntent(symbol=_symbol, side=_side, qty=_qty, limit_price=_limit, bracket=True)
        if dry_run:
            return _order_router.submit(intent, dry_run=True)
        return _order_router.submit(intent)
    except Exception as exc:  # noqa: BLE001
        log.exception("orders_test error", extra={"symbol": _symbol, "error": str(exc)})
        return {
            "accepted": False,
            "reason": f"broker_error:{exc}",
            "client_order_id": None,
        }


@app.post("/orders/cancel_all")
def cancel_all_orders():
    try:
        result = _reconcile_broker.cancel_all()
        if isinstance(result, dict):
            return result
        return {"canceled": int(result or 0)}
    except AlpacaUnauthorized:
        return {"error": "alpaca_unauthorized"}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    if not _broker.is_configured():
        return {"error": "alpaca_not_configured"}
    try:
        result = _broker.cancel_order(order_id)
        return result
    except AlpacaUnauthorized:
        return {"error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"error": f"alpaca_error:{exc}"}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/orders/open")
def list_open_orders():
    return _oms_store.get_open_orders()


@app.post("/orders/{client_order_id}/force_sync")
def force_sync_order(client_order_id: str):
    if not _broker.is_configured():
        stored = _oms_store.get_order_by_coid(client_order_id)
        if stored:
            return {"order": stored}
        raise HTTPException(status_code=503, detail="broker_unavailable")
    try:
        result = _broker.fetch_and_merge_orders(
            _oms_store, target_client_order_id=client_order_id
        )
    except AlpacaUnauthorized:
        raise HTTPException(status_code=503, detail="alpaca_unauthorized")
    except AlpacaOrderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    order = result.get("target_order")
    if order is None:
        stored = _oms_store.get_order_by_coid(client_order_id)
        if stored:
            return {"order": stored}
        raise HTTPException(status_code=404, detail="client_order_id_not_found")
    return {"order": order}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    store_snapshot = _oms_store.metrics_snapshot()
    metrics_snapshot = _oms_metrics.snapshot()
    lines: List[str] = []
    orders_by_state = store_snapshot.get("orders_by_state", {})
    for state, count in sorted(orders_by_state.items()):
        lines.append(f"oms_orders_total{{state=\"{state}\"}} {int(count)}")
    counters = metrics_snapshot.get("counters", {})
    fills_total = int(store_snapshot.get("fills_total", 0))
    lines.append(f"oms_submissions_total {int(counters.get('oms_submissions_total', 0))}")
    lines.append(f"oms_fills_total {fills_total}")
    lines.append(f"oms_rejects_total {int(counters.get('oms_rejects_total', 0))}")
    lines.append(f"oms_cancels_total {int(counters.get('oms_cancels_total', 0))}")
    lines.append(f"oms_reconcile_runs_total {int(counters.get('oms_reconcile_runs_total', 0))}")
    stream_flag = metrics_snapshot.get("flags", {}).get("alpaca_stream_connected", 0.0)
    lines.append(f"alpaca_stream_connected {int(stream_flag)}")
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/pacing")
def pacing_snapshot() -> Dict[str, Any]:
    """Expose pacing telemetry for the UI control center."""

    return load_pacing_snapshot()

# ---------- Paper controls ----------
@app.post("/paper/start", response_model=StartResp)
def paper_start(preset: Optional[str] = None):
    try:
        _kill_switch.reset_sync()
    except Exception:
        pass
    if preset:
        os.environ["RISK_PROFILE"] = preset
    start_background_runner(profile="paper")
    if runner_last_error:
        return JSONResponse(status_code=500, content={"error": runner_last_error})
    return StartResp(run_id="paper-1")

@app.get("/paper/start")
def paper_start_help():
    return JSONResponse(status_code=405, content={
        "error": "Method Not Allowed",
        "hint": "Use POST /paper/start (e.g., curl -X POST http://127.0.0.1:8000/paper/start?preset=balanced)"
    })

@app.post("/paper/stop")
def paper_stop():
    _kill_switch.engage_sync()
    return {"ok": True}

@app.post("/paper/flatten")
def paper_flatten():
    _kill_switch.engage_sync()
    try:
        subprocess.check_call([sys.executable, "backend/tools/flatten_all.py"])
    except Exception:
        pass
    return {"ok": True}


@app.get("/signals/preview")
def signals_preview(profile: str = "balanced", universe: str | None = Query(default=None)):
    symbols = None
    if universe:
        symbols = [sym.strip().upper() for sym in universe.split(",") if sym.strip()]
    try:
        bundle = _signal_engine.produce(profile=profile, universe=symbols)
        payload = bundle.model_dump(mode="json")
        return _normalize_payload(payload)
    except Exception as exc:  # noqa: BLE001
        log.info("signal preview failed", extra={"error": str(exc), "profile": profile})
        return {"error": str(exc)}


def _empty_backtest(note: str = "insufficient_data") -> Dict[str, Any]:
    zero_stats = {
        "cagr": 0.0,
        "sharpe": 0.0,
        "max_dd": 0.0,
        "winrate": 0.0,
        "avg_r": 0.0,
        "avg_trade": 0.0,
        "exposure": 0.0,
        "return_pct": 0.0,
    }
    return {"trades": [], "equity_curve": [], "stats": zero_stats, "note": note}


@app.post("/backtest/run")
def run_backtest(req: BacktestRequest):
    try:
        limit = max(int(req.days) * 390, _signal_engine.config.lookback)
        timeframe = _signal_engine.config.tf_intraday
        if req.strategy == "swing_breakout":
            timeframe = _signal_engine.config.tf_swing
        bars = _data_client.get_bars(req.symbol, timeframe=timeframe, limit=limit)
        df = bars_to_df(bars)
        if df.empty:
            return _empty_backtest()
        bundle = _signal_engine.produce(universe=[req.symbol])
        if req.strategy == "swing_breakout":
            candidate_filter = "swing_breakout"
        elif req.strategy == "intraday_momo":
            candidate_filter = "intraday_momentum"
        else:
            candidate_filter = "intraday_mean_reversion"
        candidate = next((c for c in bundle.candidates if c.kind == "equity" and c.meta.get("strategy") == candidate_filter), None)
        window = 120 if timeframe == _signal_engine.config.tf_intraday else min(len(df), req.days)
        trade_df = df.tail(max(window, 5))
        if candidate is None:
            entry_price = float(trade_df["close"].iloc[-1]) if not trade_df.empty else float(df["close"].iloc[-1])
            stop_price = entry_price * (0.99 if req.strategy != "intraday_revert" else 1.01)
            target_price = entry_price * (1.01 if req.strategy != "intraday_revert" else 0.99)
            try:
                fallback = run_trade_backtest(
                    trade_df,
                    entry=entry_price,
                    stop=stop_price,
                    target=target_price,
                    side="buy",
                    time_exit=window,
                )
                return {
                    "trades": _normalize_payload(fallback.trades),
                    "equity_curve": _normalize_payload(fallback.equity_curve),
                    "stats": _normalize_payload(fallback.stats),
                    "note": "fallback_backtest",
                }
            except Exception as exc:  # pragma: no cover - fallback safety
                log.info("fallback backtest failed", extra={"error": str(exc), "symbol": req.symbol})
                return _empty_backtest()
        result = run_trade_backtest(
            trade_df,
            entry=float(candidate.entry),
            stop=float(candidate.stop) if candidate.stop is not None else None,
            target=float(candidate.target) if candidate.target is not None else None,
            side=candidate.side,
            time_exit=window,
        )
        payload = {
            "trades": _normalize_payload(result.trades),
            "equity_curve": _normalize_payload(result.equity_curve),
            "stats": _normalize_payload(result.stats),
            "candidate": _normalize_payload(candidate.model_dump(mode="json")),
        }
        return payload
    except Exception as exc:  # noqa: BLE001
        log.info("backtest run failed", extra={"error": str(exc), "symbol": req.symbol})
        return _empty_backtest()


@app.get("/ml/status")
def ml_status():
    model = load_from_registry()
    if model is None:
        return {"model": None, "status": "missing"}
    created_at = model.created_at.isoformat() if model.created_at else None
    feature_importances: list[dict[str, float]] = []
    try:
        calibrated = getattr(model, "calibrated_model", None)
        base = None
        if calibrated is not None:
            base = getattr(calibrated, "base_estimator", None) or getattr(calibrated, "estimator", None)
        estimator = None
        if base is not None:
            estimator = getattr(base, "named_steps", {}).get("estimator")
        elif hasattr(calibrated, "named_steps"):
            estimator = getattr(calibrated, "named_steps", {}).get("estimator")
        if estimator is not None and hasattr(estimator, "coef_"):
            coefs = getattr(estimator, "coef_")
            if isinstance(coefs, (list, tuple)) or getattr(coefs, "ndim", 1) == 2:
                values = [abs(float(v)) for v in coefs[0]]
                feature_importances = [
                    {"feature": FEATURE_LIST[idx], "importance": values[idx]}
                    for idx in range(min(len(values), len(FEATURE_LIST)))
                ]
                feature_importances.sort(key=lambda item: item["importance"], reverse=True)
    except Exception:  # pragma: no cover - diagnostic only
        feature_importances = []
    return {"model": DEFAULT_MODEL_NAME, "created_at": created_at, "metrics": _normalize_payload(model.metrics or {}), "feature_importances": feature_importances}


@app.get("/ml/features")
def ml_features(symbol: str = Query(..., description="Ticker symbol")):
    try:
        features, meta = latest_feature_row(symbol, _data_client)
        row = features.iloc[-1].to_dict()
        return {"symbol": symbol.upper(), "features": _normalize_payload(row), "meta": _normalize_payload(meta)}
    except Exception as exc:  # noqa: BLE001
        log.info("ml features failed", extra={"error": str(exc), "symbol": symbol})
        return {"error": str(exc)}


@app.api_route("/ml/predict", methods=["GET", "POST"])
async def ml_predict(request: Request, symbol: str | None = Query(default=None, description="Ticker symbol")):
    body_symbol: str | None = None
    if request.method == "POST":
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            body_symbol = payload.get("symbol")

    symbol_param = body_symbol or symbol or request.query_params.get("symbol")
    if not symbol_param:
        return JSONResponse(status_code=400, content={"error": "symbol_required"})

    model = load_from_registry()
    if model is None:
        return {"model": None, "status": "missing"}

    try:
        features, meta = latest_feature_row(symbol_param, _data_client)
        proba = model.predict_proba(features)
        if isinstance(proba, list):
            p_up = float(proba[-1]) if proba else 0.0
        else:
            p_up = float(proba)
        return {"symbol": symbol_param.upper(), "p_up_15m": p_up, "model": DEFAULT_MODEL_NAME}
    except Exception as exc:  # noqa: BLE001
        log.info("ml predict failed", extra={"error": str(exc), "symbol": symbol_param})
        return {"error": str(exc)}


@app.post("/ml/train")
def ml_train(payload: TrainRequest | None = None):
    symbols = payload.symbols if payload and payload.symbols else _signal_engine.config.universe[:2]
    try:
        metrics = train_intraday_classifier(symbols, _data_client)
        return {"model": DEFAULT_MODEL_NAME, "metrics": _normalize_payload(metrics)}
    except Exception as exc:  # noqa: BLE001
        log.info("ml train failed", extra={"error": str(exc), "symbols": symbols})
        return {"error": str(exc)}


# ---------- Data endpoints ----------


@app.post("/orders/sync")
def orders_sync(status: Literal["open", "closed", "all"] = Query("all")):
    try:
        summary = _reconciler.sync_once(status_scope=status)
    except ValueError as exc:  # invalid scope
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if os.getenv("MOCK_MODE", "true").lower() in {"1", "true", "on", "yes"}:
        try:
            _reconciler.seed_mock_order()
        except Exception:
            pass
    return summary


@app.get("/trade/debug/audit_tail")
def audit_tail(n: int = Query(50, ge=0, le=500)):
    if n <= 0:
        return []

    try:
        return _audit_log.tail(n)
    except Exception as exc:  # noqa: BLE001
        log.debug("audit tail read failed: %s", exc)
        return []


@app.get("/trade/debug/reconcile_state")
def reconcile_state():
    return _reconciler.get_state_summary()


@app.get("/orders")
def orders(status: Literal["open", "closed", "all"] = Query("all")):
    try:
        normalized_orders = _reconciler.fetch_orders(status_scope=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        _execution_state.update_orders(normalized_orders)
    except Exception as exc:  # noqa: BLE001
        log.debug("execution state update failed: %s", exc)
    return normalized_orders


@app.get("/positions")
def positions():
    positions_payload = _reconciler.fetch_positions()
    try:
        _execution_state.update_positions(positions_payload)
    except Exception as exc:  # noqa: BLE001
        log.debug("execution state positions update failed: %s", exc)
    return positions_payload

# ---------- NEW: Real sentiment via Alpaca News (with graceful fallback) ----------
@app.get("/sentiment")
def sentiment(symbol: str, hours_back: int = 24, limit: int = 50):
    """
    Compute a simple sentiment score from recent Alpaca news headlines ([-1,1]).
    Returns 200 with real scores or a neutral fallback + reason.
    Caches per (symbol,hours_back,limit) for 5 minutes.
    """
    key = (symbol.upper(), int(hours_back), int(limit))
    now = time.time()
    cached = _SENT_CACHE.get(key)
    if cached:
        ts, payload = cached
        if (now - ts) < _SENT_TTL_SEC:
            payload = dict(payload)  # shallow copy
            payload["cached"] = True
            return payload

    try:
        from services.sentiment.fetchers import AlpacaNewsFetcher
        from services.sentiment.scoring import heuristic_score
    except Exception as e:
        payload = {
            "symbol": symbol.upper(),
            "score": None,
            "items": [],
            "note": f"Sentiment modules not available: {e}"
        }
        _SENT_CACHE[key] = (now, payload)
        return payload

    try:
        fetcher = AlpacaNewsFetcher()
        items = fetcher.fetch_headlines(symbol.upper(), hours_back=hours_back, limit=limit)
        if not items:
            payload = {"symbol": symbol.upper(), "score": 0.0, "items": [], "note": "No news found"}
            _SENT_CACHE[key] = (now, payload)
            return payload
        scores = [heuristic_score(i.get("headline",""), i.get("summary","")) for i in items]
        score = sum(scores)/len(scores)
        payload = {"symbol": symbol.upper(), "score": round(score, 4), "count": len(items), "items": items[:10]}
        _SENT_CACHE[key] = (now, payload)
        return payload
    except Exception as e:
        payload = {"symbol": symbol.upper(), "score": 0.0, "items": [], "note": f"Fallback: {e}"}
        _SENT_CACHE[key] = (now, payload)
        return payload

# ---------- Entrypoint ----------
def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run("backend.api:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    run()

