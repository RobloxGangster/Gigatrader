import asyncio
import inspect
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
try:
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore[assignment]

from backend.routers import (
    audit,
    broker,
    debug,
    diagnostics,
    indicators,
    logs,
    metrics,
    orchestrator,
    pnl,
    reconcile,
    risk,
    strategy,
    stream,
    trades,
    telemetry,
)
from backend.routers.deps import (
    get_kill_switch,
    get_orchestrator,
    get_stream_manager,
)
from backend.broker.adapter import get_broker as get_trade_broker
from backend.services import reconcile
from backend.services.alpaca_client import get_trading_client
from backend.services.orchestrator import get_orchestrator_status
from backend.services.orchestrator_manager import orchestrator_manager
from core.broker_config import is_mock
from core.runtime_flags import RuntimeFlags, get_runtime_flags
from core.settings import get_settings
from backend.schemas import OrderRequest, OrderResponse

load_dotenv()

settings = get_settings()
logger = logging.getLogger(__name__)


order_router = APIRouter(tags=["broker"])
_execution_log_path = Path("logs") / "execution_debug.log"


def _append_execution_log(message: str) -> None:
    try:
        _execution_log_path.parent.mkdir(parents=True, exist_ok=True)
        with _execution_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{message}\n")
    except Exception:  # pragma: no cover - logging best effort
        logger.debug("Failed to append execution log", exc_info=True)


def _configure_gigatrader_logger() -> None:
    """Ensure the shared Gigatrader logger has a sane log level."""

    gigalog = logging.getLogger("gigatrader")
    if getattr(gigalog, "_gigatrader_configured", False):  # type: ignore[attr-defined]
        return

    level = logging.INFO
    try:
        flags = get_runtime_flags()
    except Exception:  # pragma: no cover - runtime flag probe
        flags = None

    profile = None
    paper_mode = False
    if flags is not None:
        profile = str(getattr(flags, "profile", None) or "").lower() or None
        paper_mode = bool(getattr(flags, "paper_trading", False))
    if profile in {None, "paper", "dev", "development"} or paper_mode:
        level = logging.DEBUG

    gigalog.setLevel(level)
    gigalog.propagate = True
    setattr(gigalog, "_gigatrader_configured", True)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:  # pragma: no cover - defensive conversion
        return default


def normalize_order(order: Mapping[str, Any]) -> OrderResponse:
    submitted_at = order.get("submitted_at") or order.get("created_at")
    if submitted_at is not None and hasattr(submitted_at, "isoformat"):
        submitted_at = submitted_at.isoformat()
    elif submitted_at is not None:
        submitted_at = str(submitted_at)

    qty_value = order.get("qty") or order.get("quantity") or 0
    tif_value = order.get("time_in_force") or order.get("tif") or "day"
    order_type = order.get("type") or order.get("order_type") or "market"
    side_value = order.get("side") or "buy"

    raw_data: dict[str, Any] | None
    if isinstance(order, dict):
        raw_data = order
    else:
        raw_data = dict(order)

    return OrderResponse(
        id=str(order.get("id") or order.get("order_id") or order.get("id_str") or ""),
        client_order_id=order.get("client_order_id"),
        symbol=str(order.get("symbol") or order.get("ticker") or ""),
        qty=_safe_float(qty_value, 0.0) or 0.0,
        side=str(side_value).lower(),
        type=str(order_type).lower(),
        time_in_force=str(tif_value).lower(),
        status=str(order.get("status") or order.get("state") or "unknown").lower(),
        submitted_at=submitted_at,
        filled_qty=_safe_float(order.get("filled_qty")),
        filled_avg_price=_safe_float(order.get("filled_avg_price")),
        raw=raw_data,
    )


async def _place_order(payload: OrderRequest, broker: Any) -> OrderResponse:
    request_payload = payload.model_dump(exclude_none=True)
    client_order_id = request_payload.get("client_order_id")

    try:
        order = await broker.place_order(**request_payload)
    except NotImplementedError as exc:
        logger.exception("Broker adapter does not implement place_order")
        _append_execution_log(
            f"[order][failure] cid={client_order_id or 'n/a'} not_implemented: {exc}"
        )
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        _append_execution_log(
            f"[order][failure] cid={client_order_id or 'n/a'} bad_request: {exc}"
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network interaction
        logger.exception("Failed to place order with broker")
        _append_execution_log(
            f"[order][failure] cid={client_order_id or 'n/a'} broker_error: {exc}"
        )
        raise HTTPException(status_code=502, detail=f"broker_error: {exc}") from exc

    normalized = normalize_order(order)
    _append_execution_log(
        f"[order][success] cid={normalized.client_order_id or client_order_id or 'n/a'} "
        f"id={normalized.id}"
    )
    return normalized


def _broker_dependency() -> Any:
    try:
        return get_trade_broker()
    except RuntimeError as exc:
        _append_execution_log(
            f"[order][failure] cid=n/a configuration_error: {exc}"
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _create_broker_order(payload: OrderRequest, broker: Any) -> OrderResponse:
    return await _place_order(payload, broker)


@order_router.post(
    "/broker/order",
    response_model=OrderResponse,
    status_code=200,
)
async def create_broker_order(
    payload: OrderRequest, broker: Any = Depends(_broker_dependency)
) -> OrderResponse:
    """Create an order without orchestrator involvement."""

    return await _create_broker_order(payload, broker)


@order_router.post(
    "/broker/orders",
    response_model=OrderResponse,
    status_code=200,
)
async def create_broker_order_alias(
    payload: OrderRequest, broker: Any = Depends(_broker_dependency)
) -> OrderResponse:
    """Backward compatible alias for order creation."""

    return await _create_broker_order(payload, broker)


def _ensure_log_directories() -> None:
    base_paths = [
        Path("logs"),
        Path("logs/backend"),
        Path("logs/diagnostics"),
        Path("logs/audit"),
    ]
    for path in base_paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception:  # pragma: no cover - best effort filesystem guard
            pass


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _ensure_log_directories()
    _configure_gigatrader_logger()
    flags = get_runtime_flags()
    profile = "paper" if flags.paper_trading else "live"
    logger.info(
        "profile=%s broker=%s dry_run=%s mock_mode=%s",
        profile,
        flags.broker,
        flags.dry_run,
        flags.mock_mode,
    )
    try:
        loop = asyncio.get_event_loop()
        get_stream_manager().start(loop)
    except Exception:
        pass

    if not flags.mock_mode:
        try:
            from backend.services.reconcile import pull_all_if_live

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, pull_all_if_live)
        except Exception:
            pass

    yield


app = FastAPI(title="Gigatrader API", lifespan=_lifespan)
root_router = APIRouter()

ui_origins = {
    f"http://127.0.0.1:{settings.ui_port}",
    f"http://localhost:{settings.ui_port}",
}
cors_origins = sorted(ui_origins | {settings.api_base})

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(order_router)
for alias in ("/api", "/v1"):
    app.include_router(order_router, prefix=alias, tags=["broker-compat"])

PRIMARY_ROUTERS: list[tuple[str, Any, list[str]]] = [
    ("/broker", broker.router, ["broker"]),
    ("/stream", stream.router, ["stream"]),
    ("/strategy", strategy.router, ["strategy"]),
    ("/risk", risk.router, ["risk"]),
    ("/orchestrator", orchestrator.router, ["orchestrator"]),
    ("/pnl", pnl.router, ["pnl"]),
    ("/metrics", metrics.router, ["metrics"]),
    ("", telemetry.router, ["telemetry"]),
    ("/logs", logs.router, ["logs"]),
    ("/trades", trades.router, ["trades"]),
    ("/indicators", indicators.router, ["indicators"]),
    ("/features", indicators.router, ["features"]),
    ("/diagnostics", diagnostics.router, ["diagnostics"]),
    ("/debug", debug.router, ["debug"]),
    ("/reconcile", reconcile.router, ["reconcile"]),
    ("/audit", audit.router, ["audit"]),
]

for prefix, router, tags in PRIMARY_ROUTERS:
    app.include_router(router, prefix=prefix, tags=tags)

for alias in ("/api", "/v1"):
    for prefix, router, tags in PRIMARY_ROUTERS:
        compat_tag = [f"{tags[0]}-compat"] if tags else None
        app.include_router(router, prefix=f"{alias}{prefix}", tags=compat_tag)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _register_compat_route(
    path: str,
    endpoint: Callable[..., Any],
    methods: Sequence[str],
    *,
    tag: str | None = None,
) -> None:
    compat_tags = [f"{tag}-compat"] if tag else None
    for alias in ("/api", "/v1"):
        app.add_api_route(
            f"{alias}{path}", endpoint, methods=list(methods), tags=compat_tags
        )


@root_router.get("/health")
async def health() -> Dict[str, Any]:
    """Return a fast, side-effect free health snapshot."""

    try:
        flags = get_runtime_flags()
    except Exception:  # pragma: no cover - defensive runtime flag guard
        flags = None

    orchestrator_status_obj = None
    try:
        orchestrator_status_obj = get_orchestrator_status()
        orchestrator_snapshot = orchestrator_status_obj.model_dump()
    except Exception as exc:  # pragma: no cover - defensive health guard
        orchestrator_snapshot = {"state": "unknown", "error": str(exc)}
    try:
        manager_snapshot = orchestrator_manager.get_status()
    except Exception as exc:  # pragma: no cover - defensive health guard
        manager_snapshot = {"state": "unknown", "error": str(exc), "thread_alive": False}

    profile_value = getattr(flags, "profile", None) or getattr(settings.runtime, "profile", "paper")
    broker_value = getattr(flags, "broker", getattr(settings.runtime, "broker", "alpaca"))
    dry_run_flag = bool(getattr(flags, "dry_run", getattr(settings.runtime, "dry_run", False)))
    mock_mode_flag = bool(getattr(flags, "mock_mode", False))
    paper_mode_flag = bool(getattr(flags, "paper_trading", profile_value != "live"))

    orchestrator_state = str(orchestrator_snapshot.get("state", "stopped"))
    kill_reason = orchestrator_snapshot.get("kill_switch_reason")
    kill_engaged = bool(orchestrator_snapshot.get("kill_switch_engaged"))
    kill_can_reset = bool(orchestrator_snapshot.get("kill_switch_can_reset", True))
    kill_label = "Triggered" if kill_engaged else "Standby"
    if orchestrator_status_obj is not None:
        kill_reason = orchestrator_status_obj.kill_switch.reason
        kill_engaged = orchestrator_status_obj.kill_switch.engaged
        kill_can_reset = orchestrator_status_obj.kill_switch.can_reset
        kill_label = "Triggered" if kill_engaged else "Standby"
        if kill_engaged and kill_reason:
            kill_label = f"Triggered ({kill_reason})"

    payload: Dict[str, Any] = {
        "status": "ok",
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile_value,
        "broker": broker_value,
        "orchestrator_state": orchestrator_state,
        "kill_switch": kill_label,
        "kill_switch_engaged": kill_engaged,
        "kill_switch_reason": kill_reason,
        "kill_switch_can_reset": kill_can_reset,
        "can_trade": bool(orchestrator_snapshot.get("can_trade", False)),
        "trade_guard_reason": orchestrator_snapshot.get("trade_guard_reason"),
        "dry_run": dry_run_flag,
        "paper_mode": paper_mode_flag,
        "mock_mode": mock_mode_flag,
        "stream_source": orchestrator_snapshot.get("market_data_source", "unknown"),
        "orchestrator": {**orchestrator_snapshot, "manager": manager_snapshot},
        "manager": manager_snapshot,
    }

    payload["thread_alive"] = bool(manager_snapshot.get("thread_alive"))
    payload["restart_count"] = int(
        orchestrator_snapshot.get("restart_count")
        or manager_snapshot.get("restart_count")
        or 0
    )
    payload["last_error"] = (
        orchestrator_snapshot.get("last_error")
        or manager_snapshot.get("last_error")
        or orchestrator_snapshot.get("error")
        or manager_snapshot.get("error")
    )

    last_error = orchestrator_snapshot.get("last_error") or manager_snapshot.get("last_error")
    if last_error:
        payload["error"] = last_error

    return payload


@root_router.get("/debug/runtime", response_model=RuntimeFlags)
async def debug_runtime(flags: RuntimeFlags = Depends(get_runtime_flags)) -> RuntimeFlags:
    return flags
@app.get("/version")
def version() -> Dict[str, str]:
    return {"version": os.getenv("APP_VERSION", "dev")}


_register_compat_route("/health", health, ["GET"], tag="health")
_register_compat_route("/version", version, ["GET"], tag="version")

app.include_router(root_router)


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)

from backend.routes import backtests_compat  # noqa: E402
from backend.routers import options as options_router  # noqa: E402
from backend.routes import logs as logs_routes  # noqa: E402
from backend.routes import pacing as pacing_routes  # noqa: E402
from backend.routes import backtest_v2 as backtest_v2_routes  # noqa: E402
from backend.routes import ml as ml_routes  # noqa: E402
from backend.routes import ml_calibration as ml_calibration_routes  # noqa: E402
from backend.routes import alpaca_live as alpaca_live_routes  # noqa: E402
from backend.routes import broker as broker_routes  # noqa: E402

app.include_router(ml_routes.router)
app.include_router(ml_calibration_routes.router)
app.include_router(backtest_v2_routes.router)
app.include_router(backtests_compat.router)
app.include_router(options_router.router)
app.include_router(logs_routes.router)
app.include_router(pacing_routes.router)
app.include_router(alpaca_live_routes.router)
app.include_router(broker_routes.router)


class StartReq(BaseModel):
    preset: str | None = None


_last_reconcile: Optional[float] = None


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@app.get("/status")
def status() -> Dict[str, Any]:
    """Return the orchestrator status in a dict-safe payload for the UI."""

    try:
        raw_snapshot = get_orchestrator_status()
    except Exception:  # pragma: no cover - defensive status guard
        raw_snapshot = None

    if isinstance(raw_snapshot, BaseModel):
        snapshot: Dict[str, Any] = (
            raw_snapshot.model_dump() if hasattr(raw_snapshot, "model_dump") else raw_snapshot.dict()
        )
    elif isinstance(raw_snapshot, dict):
        snapshot = raw_snapshot
    else:
        encoded = jsonable_encoder(raw_snapshot) if raw_snapshot is not None else {}
        snapshot = encoded if isinstance(encoded, dict) else {}

    state = str(snapshot.get("state") or "stopped")
    transition = snapshot.get("transition")
    phase = snapshot.get("phase") or state
    running = state == "running"

    kill_info = snapshot.get("kill_switch") if isinstance(snapshot.get("kill_switch"), dict) else None
    if not isinstance(kill_info, dict):
        kill_info = {
            "engaged": bool(snapshot.get("kill_switch_engaged", False)),
            "reason": snapshot.get("kill_switch_reason"),
            "can_reset": bool(snapshot.get("kill_switch_can_reset", True)),
        }

    will_trade_at_open = bool(snapshot.get("will_trade_at_open") or False)
    preopen_queue_count = int(snapshot.get("preopen_queue_count") or 0)

    runtime_settings = getattr(settings, "runtime", None)
    broker_mode = getattr(runtime_settings, "broker_mode", "paper") if runtime_settings else "paper"
    dry_run_flag = bool(getattr(runtime_settings, "dry_run", False)) if runtime_settings else False
    broker_name = getattr(runtime_settings, "broker", "alpaca") if runtime_settings else "alpaca"
    broker_profile = snapshot.get("broker")
    if isinstance(broker_profile, dict):
        broker_name = str(broker_profile.get("broker") or broker_name)

    try:
        halted = bool(get_kill_switch().engaged_sync())
    except Exception:  # pragma: no cover - defensive kill switch guard
        halted = bool(kill_info.get("engaged"))

    payload: Dict[str, Any] = {
        "state": state,
        "transition": transition,
        "phase": phase,
        "running": running,
        "will_trade_at_open": will_trade_at_open,
        "preopen_queue_count": preopen_queue_count,
        "broker": broker_name,
        "profile": snapshot.get("profile"),
        "paper": broker_mode != "live",
        "broker_mode": broker_mode,
        "dry_run": dry_run_flag,
        "halted": halted,
        "last_run_id": snapshot.get("last_run_id"),
        "last_tick_ts": snapshot.get("last_tick_ts"),
        "ok": bool(snapshot.get("ok", True)),
        "kill_switch": kill_info,
        "kill_switch_engaged": bool(kill_info.get("engaged")),
        "kill_switch_reason": kill_info.get("reason"),
        "kill_switch_can_reset": bool(kill_info.get("can_reset", True)),
    }

    for key in (
        "thread_alive",
        "start_attempt_ts",
        "last_shutdown_reason",
        "last_error",
        "last_error_at",
        "last_error_stack",
        "last_heartbeat",
        "uptime_secs",
        "uptime_label",
        "uptime",
        "restart_count",
        "can_trade",
        "trade_guard_reason",
        "market_data_source",
        "market_state",
        "mock_mode",
        "manager",
        "kill_switch_history",
        "last_decision_at",
        "last_decision_ts",
        "last_decision_signals",
        "last_decision_orders",
        "last_error_ts",
    ):
        if key in snapshot and key not in payload:
            payload[key] = snapshot.get(key)

    return payload


_register_compat_route("/status", status, ["GET"], tag="status")


@app.post("/orchestrator/reconcile")
def orchestrator_reconcile() -> Dict[str, Any]:
    global _last_reconcile
    orchestrator = get_orchestrator()
    if is_mock():
        _last_reconcile = time.time()
        orchestrator.mark_tick()
        return {"ok": True, "snapshot": {"mode": "mock"}}
    try:
        snapshot = reconcile.pull_all_if_live()
    except Exception as exc:  # pragma: no cover - network path
        orchestrator.set_last_error(str(exc))
        raise HTTPException(502, f"Reconcile failed: {exc}") from exc
    _last_reconcile = time.time()
    orchestrator.mark_tick()
    orchestrator.set_last_error(None)
    return {
        "ok": True,
        "snapshot": snapshot,
        "last_reconcile": _format_ts(_last_reconcile),
    }


_register_compat_route(
    "/orchestrator/reconcile", orchestrator_reconcile, ["POST"], tag="orchestrator"
)


@app.get("/orchestrator/start")
async def orchestrator_start_get():
    return await orchestrator.orchestrator_start()


@app.get("/orchestrator/stop")
async def orchestrator_stop_get():
    return await orchestrator.orchestrator_stop()


_register_compat_route(
    "/orchestrator/start", orchestrator_start_get, ["GET"], tag="orchestrator"
)
_register_compat_route(
    "/orchestrator/stop", orchestrator_stop_get, ["GET"], tag="orchestrator"
)


@app.post("/paper/start")
def paper_start(req: StartReq | None = None):
    preset = req.preset if req else None
    return get_orchestrator().start_sync(mode="paper", preset=preset)


_register_compat_route("/paper/start", paper_start, ["POST"], tag="paper")


@app.post("/paper/stop")
def paper_stop():
    return get_orchestrator().stop_sync()


_register_compat_route("/paper/stop", paper_stop, ["POST"], tag="paper")


@app.post("/paper/flatten")
def flatten_and_halt():
    get_kill_switch().engage_sync(reason="manual_flatten")
    return {"ok": True, "halted": True}


_register_compat_route("/paper/flatten", flatten_and_halt, ["POST"], tag="paper")


@app.post("/orders/cancel_all")
def cancel_all_orders() -> Dict[str, Any]:
    if is_mock():
        return {"canceled": 0, "mock_mode": True}
    try:
        client = get_trading_client()
        result = client.cancel_orders()
        count = 0
        if isinstance(result, Iterable):
            count = len(list(result))
        elif result is None:
            count = 0
        else:
            count = 1
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(502, f"Cancel all failed: {exc}") from exc
    return {"canceled": count}


_register_compat_route("/orders/cancel_all", cancel_all_orders, ["POST"], tag="orders")


@app.post("/live/start")
def live_start(req: StartReq | None = None):
    if os.getenv("LIVE_TRADING", "false").lower() not in ("1", "true", "yes"):
        raise HTTPException(403, "LIVE_TRADING env not enabled")
    preset = req.preset if req else None
    return get_orchestrator().start_sync(mode="live", preset=preset)


_register_compat_route("/live/start", live_start, ["POST"], tag="live")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", "8000"))
    print(f"\n=== Gigatrader API starting on 127.0.0.1:{port} ===")
    uvicorn.run("backend.api:app", host="127.0.0.1", port=port, reload=False)
