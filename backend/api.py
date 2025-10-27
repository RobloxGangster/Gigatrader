import asyncio
import inspect
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.routers import (
    audit,
    broker,
    diagnostics,
    logs,
    orchestrator,
    pnl,
    reconcile,
    risk,
    strategy,
    stream,
    telemetry,
)
from backend.routers.deps import (
    BrokerService,
    get_broker,
    get_kill_switch,
    get_orchestrator,
    get_stream_manager,
)
from backend.services import reconcile
from backend.services.alpaca_client import get_trading_client
from backend.services.stream_factory import StreamService
from core.broker_config import is_mock
from core.runtime_flags import RuntimeFlags, get_runtime_flags
from core.settings import get_settings

load_dotenv()

settings = get_settings()
logger = logging.getLogger(__name__)


EXECUTION_LOG_PATH = Path("logs/execution_debug.log")


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

PRIMARY_ROUTERS: list[tuple[str, Any, list[str]]] = [
    ("/broker", broker.router, ["broker"]),
    ("/stream", stream.router, ["stream"]),
    ("/strategy", strategy.router, ["strategy"]),
    ("/risk", risk.router, ["risk"]),
    ("/orchestrator", orchestrator.router, ["orchestrator"]),
    ("/pnl", pnl.router, ["pnl"]),
    ("/telemetry", telemetry.router, ["telemetry"]),
    ("/logs", logs.router, ["logs"]),
    ("/diagnostics", diagnostics.router, ["diagnostics"]),
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
async def health(
    stream: StreamService = Depends(get_stream_manager),
    broker: BrokerService = Depends(get_broker),
    orchestrator: Any = Depends(get_orchestrator),
    kill_switch: Any = Depends(get_kill_switch),
) -> Dict[str, Any]:
    """
    This must NOT throw.
    """

    try:
        flags = get_runtime_flags()
    except Exception:  # pragma: no cover - defensive runtime flag guard
        flags = None

    profile_value = getattr(flags, "profile", None) or getattr(settings, "profile", None)
    if not profile_value:
        profile_value = getattr(settings.runtime, "profile", "paper")

    broker_name = getattr(flags, "broker", None) or getattr(settings.runtime, "broker", "Alpaca")
    broker_impl = broker_name
    orchestrator_state = "Unknown"
    stream_source = "alpaca/paper"
    kill_label = "Standby"
    ok = True
    error: str | None = None

    dry_run_flag = bool(getattr(flags, "dry_run", getattr(settings.runtime, "dry_run", False)))
    mock_mode_flag = bool(getattr(flags, "mock_mode", False))
    paper_mode_flag = bool(getattr(flags, "paper_trading", profile_value != "live"))

    try:
        adapter = getattr(broker, "adapter", None)
        if adapter is not None:
            broker_impl = getattr(adapter, "name", broker_impl) or broker_impl
            if hasattr(adapter, "ping"):
                await _maybe_await(adapter.ping())
    except Exception as exc:  # pragma: no cover - defensive ping guard
        ok = False
        error = str(exc)

    try:
        orchestrator_snapshot = await _maybe_await(orchestrator.status())
        if isinstance(orchestrator_snapshot, dict):
            orchestrator_state = str(
                orchestrator_snapshot.get("state")
                or ("Running" if orchestrator_snapshot.get("running") else "Stopped")
                or "Unknown"
            )
    except Exception as exc:  # pragma: no cover - defensive snapshot guard
        orchestrator_state = "Error"
        ok = False
        error = error or str(exc)

    try:
        stream_status_raw = await _maybe_await(stream.status())
        if isinstance(stream_status_raw, dict):
            stream_source = str(stream_status_raw.get("source") or stream_source)
            if not stream_status_raw.get("ok", True):
                ok = False
                error = error or str(stream_status_raw.get("error") or "Stream unavailable")
            if "mock" in stream_source.lower():
                mock_mode_flag = True
            dry_run_flag = bool(stream_status_raw.get("dry_run", dry_run_flag))
        elif stream_status_raw is False:
            ok = False
            error = error or "Stream unavailable"
    except Exception as exc:  # pragma: no cover - defensive stream guard
        stream_source = "unknown"
        ok = False
        error = error or str(exc)

    try:
        kill_engaged = kill_switch.engaged_sync()
        kill_label = "Triggered" if kill_engaged else "Standby"
        if kill_engaged:
            ok = False
    except Exception:  # pragma: no cover - defensive kill switch guard
        kill_label = "Unknown"

    if broker_name.lower() == "alpaca" and (
        not settings.alpaca.key_id or not settings.alpaca.secret_key
    ):
        ok = False
        error = error or "Missing APCA_KEY_ID"

    payload: Dict[str, Any] = {
        "ok": ok,
        "profile": profile_value,
        "broker": broker_impl or broker_name,
        "orchestrator_state": orchestrator_state,
        "stream_source": stream_source,
        "kill_switch": kill_label,
        "dry_run": dry_run_flag,
        "paper_mode": paper_mode_flag,
        "mock_mode": mock_mode_flag,
    }
    if error:
        payload["error"] = error
    return payload


@root_router.get("/debug/runtime", response_model=RuntimeFlags)
async def debug_runtime(flags: RuntimeFlags = Depends(get_runtime_flags)) -> RuntimeFlags:
    return flags


def _tail_file(path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return list(deque(handle, maxlen=limit))
    except Exception:  # pragma: no cover - defensive file guard
        return []


@root_router.get("/debug/execution_tail")
async def execution_tail(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    lines = _tail_file(EXECUTION_LOG_PATH, limit)
    return {"path": str(EXECUTION_LOG_PATH), "lines": [line.rstrip("\n") for line in lines]}


@app.get("/version")
def version() -> Dict[str, str]:
    return {"version": os.getenv("APP_VERSION", "dev")}


_register_compat_route("/health", health, ["GET"], tag="health")
_register_compat_route("/version", version, ["GET"], tag="version")

app.include_router(root_router)

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
def status():
    snapshot = get_orchestrator().status()
    kill_switch = get_kill_switch()
    return {
        "running": snapshot.get("running"),
        "profile": snapshot.get("profile"),
        "paper": settings.runtime.broker_mode != "live",
        "broker": settings.runtime.broker,
        "broker_mode": settings.runtime.broker_mode,
        "dry_run": settings.runtime.dry_run,
        "halted": kill_switch.engaged_sync(),
        "last_run_id": snapshot.get("last_run_id"),
        "last_tick_ts": snapshot.get("last_tick_ts"),
        "ok": True,
    }


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
    get_kill_switch().engage_sync()
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
