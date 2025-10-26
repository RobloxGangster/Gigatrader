import asyncio
import inspect
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from backend.services.stream_factory import StreamService, make_stream_service
from core.broker_config import is_mock
from core.runtime_flags import get_runtime_flags
from core.settings import get_settings

load_dotenv()

settings = get_settings()
logger = logging.getLogger(__name__)


def _ensure_log_directories() -> None:
    base_paths = [
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

    skip_reconcile = os.getenv("MOCK_MODE", "").lower() in ("1", "true", "yes", "on")
    if not skip_reconcile:
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
    stream: StreamService = Depends(make_stream_service),
    broker: BrokerService = Depends(get_broker),
    orchestrator: Any = Depends(get_orchestrator),
) -> JSONResponse:
    flags = get_runtime_flags()
    status: str = "ok"
    orchestrator_snapshot: Dict[str, Any] = {}
    try:
        orchestrator_snapshot = await _maybe_await(orchestrator.status())
    except Exception as exc:  # pragma: no cover - defensive snapshot guard
        status = "degraded"
        orchestrator_snapshot = {"running": False, "last_error": str(exc)}
    orchestrator_snapshot.setdefault("state", "stopped")

    try:
        stream_status_raw = await _maybe_await(stream.status())
    except Exception as exc:  # pragma: no cover - defensive
        status = "degraded"
        stream_status_raw = {"ok": False, "error": str(exc), "source": "mock"}

    stream_source = "mock" if flags.mock_mode else "alpaca"
    stream_ok = True
    if isinstance(stream_status_raw, dict):
        stream_source = str(stream_status_raw.get("source") or stream_source)
        stream_ok = bool(
            stream_status_raw.get("ok")
            or stream_status_raw.get("healthy")
            or stream_status_raw.get("online")
        )
    elif isinstance(stream_status_raw, bool):
        stream_ok = stream_status_raw
    if not stream_ok:
        status = "degraded"

    broker_source = "mock" if flags.mock_mode else "alpaca"
    broker_status: Dict[str, Any] = {
        "source": broker_source,
        "paper": flags.paper_trading,
        "mode": "mock"
        if flags.mock_mode
        else ("paper" if flags.paper_trading else "live"),
        "base_url": flags.alpaca_base_url,
        "ok": True,
    }

    try:
        if hasattr(broker, "ping"):
            await _maybe_await(broker.ping())
    except Exception as exc:  # pragma: no cover - defensive ping guard
        broker_status["ok"] = False
        broker_status["ping_error"] = str(exc)
        status = "degraded"

    if broker_source == "alpaca" and not (
        flags.alpaca_key and flags.alpaca_secret and flags.alpaca_base_url
    ):
        broker_status["ok"] = False
        broker_status.setdefault("ping_error", "alpaca_credentials_missing")
        status = "degraded"

    payload = {
        "status": status,
        "ok": status == "ok",
        "mock_mode": flags.mock_mode,
        "paper_mode": flags.paper_trading,
        "dry_run": flags.dry_run,
        "profile": "paper" if flags.paper_trading else "live",
        "broker": broker_source,
        "broker_details": broker_status,
        "stream": stream_source,
        "stream_details": stream_status_raw,
        "orchestrator": orchestrator_snapshot,
    }

    if status != "ok":
        payload.setdefault("error", "degraded")

    return JSONResponse(payload, status_code=200)


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
