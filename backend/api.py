import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
from backend.routers.deps import get_kill_switch, get_orchestrator, get_stream_manager
from backend.services import reconcile
from backend.services.alpaca_client import get_trading_client
from core.broker_config import is_mock
from core.runtime_flags import get_runtime_flags
from core.settings import get_settings

load_dotenv()

app = FastAPI(title="Gigatrader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8501", "http://localhost:8501"],
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


@app.get("/health")
def health() -> Dict[str, Any]:
    flags = get_runtime_flags()
    orchestrator = get_orchestrator()
    orchestrator_status = orchestrator.status()
    try:
        stream_status = get_stream_manager().status()
    except Exception as exc:  # pragma: no cover - defensive
        stream_status = {"status": "error", "last_error": str(exc)}

    broker_status = {
        "source": "mock" if flags.mock_mode else "alpaca",
        "paper": flags.paper_trading,
    }

    return {
        "ok": True,
        "mode": {"mock_mode": flags.mock_mode, "paper": flags.paper_trading},
        "orchestrator": orchestrator_status,
        "stream": stream_status,
        "broker": broker_status,
    }


@app.get("/version")
def version() -> Dict[str, str]:
    return {"version": os.getenv("APP_VERSION", "dev")}


_register_compat_route("/health", health, ["GET"], tag="health")
_register_compat_route("/version", version, ["GET"], tag="version")

from backend.routes import backtests_compat  # noqa: E402
from backend.routes import options as options_routes  # noqa: E402
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
app.include_router(options_routes.router)
app.include_router(logs_routes.router)
app.include_router(pacing_routes.router)
app.include_router(alpaca_live_routes.router)
app.include_router(broker_routes.router)


@app.on_event("startup")
async def _startup_reconcile():
    try:
        loop = asyncio.get_event_loop()
        get_stream_manager().start(loop)
    except Exception:
        pass
    if os.getenv("MOCK_MODE", "").lower() in ("1", "true", "yes", "on"):
        return
    try:
        from backend.services.reconcile import pull_all_if_live

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, pull_all_if_live)
    except Exception:
        pass


class StartReq(BaseModel):
    preset: str | None = None


_last_reconcile: Optional[float] = None


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@app.get("/status")
def status():
    settings = get_settings()
    snapshot = get_orchestrator().status()
    kill_switch = get_kill_switch()
    return {
        "running": snapshot.get("running"),
        "profile": snapshot.get("profile"),
        "paper": os.getenv("TRADING_MODE", "paper") == "paper",
        "broker": settings.runtime.broker,
        "dry_run": settings.runtime.dry_run,
        "halted": kill_switch.engaged_sync(),
        "last_run_id": snapshot.get("last_run_id"),
        "last_tick_ts": snapshot.get("last_tick_ts"),
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
