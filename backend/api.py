import asyncio
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.market.stream_manager import StreamManager
from backend.services import reconcile
from backend.services.alpaca_client import get_trading_client
from core.broker_config import is_mock
from core.kill_switch import KillSwitch

load_dotenv()

app = FastAPI(title="Gigatrader API")
stream_manager = StreamManager()
stream_router = APIRouter()

from backend.routes import backtests_compat  # noqa: E402
from backend.routes import options as options_routes  # noqa: E402
from backend.routes import logs as logs_routes  # noqa: E402
from backend.routes import pacing as pacing_routes  # noqa: E402
from backend.routes import backtest_v2 as backtest_v2_routes  # noqa: E402
from backend.routes import ml as ml_routes  # noqa: E402
from backend.routes import ml_calibration as ml_calibration_routes  # noqa: E402
from backend.routes import alpaca_live as alpaca_live_routes  # noqa: E402
from backend.routes import broker as broker_routes  # noqa: E402
from backend.routes import health as health_routes  # noqa: E402

app.include_router(ml_routes.router)
app.include_router(ml_calibration_routes.router)
app.include_router(backtest_v2_routes.router)
app.include_router(backtests_compat.router)
app.include_router(options_routes.router)
app.include_router(logs_routes.router)
app.include_router(pacing_routes.router)
app.include_router(alpaca_live_routes.router)
app.include_router(broker_routes.router)
app.include_router(health_routes.router)


@app.on_event("startup")
async def _startup_reconcile():
    try:
        loop = asyncio.get_event_loop()
        stream_manager.start(loop)
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


_kill_switch = KillSwitch()


_runner_thread = None
_running = False
_profile = "paper"
_last_run_id: Optional[str] = None


def _mark_tick() -> None:
    _orchestrator_meta["last_tick_ts"] = time.time()


def _start_trading(mode: str, preset: Optional[str] = None) -> Dict[str, Any]:
    global _runner_thread, _running, _profile, _last_run_id
    if _running:
        return {"run_id": _last_run_id or "active"}

    if mode == "paper":
        os.environ["TRADING_MODE"] = "paper"
        os.environ["ALPACA_PAPER"] = "true"
    else:
        os.environ["TRADING_MODE"] = "live"
        os.environ["ALPACA_PAPER"] = "false"

    if preset:
        os.environ["RISK_PROFILE"] = preset

    _profile = mode
    _running = True
    _mark_tick()
    _orchestrator_meta["last_error"] = None
    _last_run_id = f"{mode}-{int(time.time())}"
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id": _last_run_id}


def _stop_trading() -> Dict[str, Any]:
    global _running
    _running = False
    _mark_tick()
    try:
        _kill_switch.engage_sync()
    except Exception:
        pass
    return {"ok": True}


class StartReq(BaseModel):
    preset: str | None = None


class StrategyConfig(BaseModel):
    preset: str = "balanced"
    enabled: bool = True
    strategies: Dict[str, bool] = Field(
        default_factory=lambda: {
            "intraday_momo": True,
            "intraday_revert": True,
            "swing_breakout": False,
        }
    )
    confidence_threshold: float = 0.55
    expected_value_threshold: float = 0.0
    universe: List[str] = Field(
        default_factory=lambda: ["AAPL", "MSFT", "NVDA", "SPY"]
    )
    cooldown_sec: int = 30
    pacing_per_minute: int = 12
    dry_run: bool = False


class StrategyConfigUpdate(BaseModel):
    preset: Optional[str] = None
    enabled: Optional[bool] = None
    strategies: Optional[Dict[str, bool]] = None
    confidence_threshold: Optional[float] = None
    expected_value_threshold: Optional[float] = None
    universe: Optional[List[str]] = None
    cooldown_sec: Optional[int] = None
    pacing_per_minute: Optional[int] = None
    dry_run: Optional[bool] = None


class RiskConfig(BaseModel):
    daily_loss_limit: float = 2000.0
    max_positions: int = 10
    per_symbol_notional: float = 20000.0
    portfolio_notional: float = 100000.0
    bracket_enabled: bool = True
    kill_switch: bool = False


class RiskConfigUpdate(BaseModel):
    daily_loss_limit: Optional[float] = None
    max_positions: Optional[int] = None
    per_symbol_notional: Optional[float] = None
    portfolio_notional: Optional[float] = None
    bracket_enabled: Optional[bool] = None


def _run_runner():
    global _running
    try:
        from services.runtime import runner as R
        R.main()
    finally:
        _running = False


@stream_router.get("/stream/status")
def stream_status() -> dict:
    return stream_manager.status()


@stream_router.post("/stream/start")
def stream_start() -> Dict[str, Any]:
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    stream_manager.start(loop)
    return stream_manager.status()


@stream_router.post("/stream/stop")
def stream_stop() -> Dict[str, Any]:
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    stream_manager.stop(loop)
    return stream_manager.status()


app.include_router(stream_router)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


_config_lock = threading.Lock()
_strategy_config = StrategyConfig()
_risk_config = RiskConfig()
_last_reconcile: Optional[float] = None
_orchestrator_meta: Dict[str, Any] = {
    "last_error": None,
    "last_tick_ts": None,
    "routed_orders_24h": 0,
}


@app.get("/status")
def status():
    return {
        "running": _running,
        "profile": _profile,
        "paper": os.getenv("TRADING_MODE","paper")=="paper",
        "halted": _kill_switch.engaged_sync(),
        "last_run_id": _last_run_id,
        "last_tick_ts": _format_ts(_orchestrator_meta.get("last_tick_ts")),
    }


@app.get("/orchestrator/status")
def orchestrator_status() -> Dict[str, Any]:
    return {
        "running": _running,
        "profile": _profile,
        "last_error": _orchestrator_meta.get("last_error"),
        "last_tick_ts": _format_ts(_orchestrator_meta.get("last_tick_ts")),
        "routed_orders_24h": int(_orchestrator_meta.get("routed_orders_24h") or 0),
        "kill_switch": _kill_switch.engaged_sync(),
    }


@app.post("/orchestrator/start")
def orchestrator_start(req: StartReq | None = None) -> Dict[str, Any]:
    preset = req.preset if req else None
    result = _start_trading("paper", preset)
    return {"ok": True, **result}


@app.post("/orchestrator/stop")
def orchestrator_stop() -> Dict[str, Any]:
    return _stop_trading()


@app.post("/orchestrator/reconcile")
def orchestrator_reconcile() -> Dict[str, Any]:
    global _last_reconcile
    if is_mock():
        _last_reconcile = time.time()
        return {"ok": True, "snapshot": {"mode": "mock"}}
    try:
        snapshot = reconcile.pull_all_if_live()
    except Exception as exc:  # pragma: no cover - network path
        _orchestrator_meta["last_error"] = str(exc)
        raise HTTPException(502, f"Reconcile failed: {exc}") from exc
    _last_reconcile = time.time()
    _mark_tick()
    return {"ok": True, "snapshot": snapshot, "last_reconcile": _format_ts(_last_reconcile)}


@app.post("/paper/start")
def paper_start(req: StartReq | None = None):
    preset = req.preset if req else None
    return _start_trading("paper", preset)


@app.post("/paper/stop")
def paper_stop():
    return _stop_trading()


@app.post("/paper/flatten")
def flatten_and_halt():
    _kill_switch.engage_sync()
    return {"ok": True, "halted": True}


@app.get("/strategy/config")
def get_strategy_config() -> Dict[str, Any]:
    with _config_lock:
        payload = _strategy_config.model_dump()
    payload.setdefault("preset", _strategy_config.preset)
    payload["mock_mode"] = is_mock()
    return payload


@app.post("/strategy/config")
def update_strategy_config(req: StrategyConfigUpdate) -> Dict[str, Any]:
    data = req.model_dump(exclude_unset=True)
    with _config_lock:
        current = _strategy_config.model_dump()
        current.update(data)
        current["strategies"] = {
            **_strategy_config.strategies,
            **(data.get("strategies") or {}),
        }
        global _strategy_config
        _strategy_config = StrategyConfig(**current)
    _mark_tick()
    return _strategy_config.model_dump()


@app.get("/risk/config")
def get_risk_config() -> Dict[str, Any]:
    with _config_lock:
        snapshot = _risk_config.model_dump()
    snapshot["kill_switch"] = _kill_switch.engaged_sync()
    snapshot["mock_mode"] = is_mock()
    return snapshot


@app.post("/risk/config")
def update_risk_config(req: RiskConfigUpdate) -> Dict[str, Any]:
    data = req.model_dump(exclude_unset=True)
    with _config_lock:
        current = _risk_config.model_dump()
        current.update(data)
        global _risk_config
        _risk_config = RiskConfig(**current)
    return get_risk_config()


@app.post("/killswitch/engage")
def engage_kill_switch() -> Dict[str, Any]:
    _kill_switch.engage_sync()
    _orchestrator_meta["last_error"] = "kill_switch_engaged"
    return {"ok": True, "kill_switch": True, "timestamp": _utc_now()}


@app.post("/killswitch/reset")
def reset_kill_switch() -> Dict[str, Any]:
    _kill_switch.reset_sync()
    return {"ok": True, "kill_switch": False, "timestamp": _utc_now()}


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


@app.get("/pnl/summary")
def pnl_summary() -> Dict[str, Any]:
    if is_mock():
        return {
            "realized_today": 0.0,
            "unrealized": 0.0,
            "total": 0.0,
            "day_pl_pct": 0.0,
        }
    try:
        acct = reconcile.pull_account()
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(502, f"Account fetch failed: {exc}") from exc
    realized = float(acct.get("daytrade_pl") or acct.get("day_pl") or 0.0)
    unrealized = float(
        acct.get("unrealized_pl")
        or acct.get("unrealized_intraday_pl")
        or 0.0
    )
    equity = float(acct.get("equity") or 0.0)
    last_equity = float(acct.get("last_equity") or (equity or 1.0))
    day_pl_pct = 0.0
    if last_equity:
        day_pl_pct = (equity - last_equity) / float(last_equity)
    return {
        "realized_today": realized,
        "unrealized": unrealized,
        "total": realized + unrealized,
        "day_pl_pct": day_pl_pct,
    }


@app.get("/telemetry/exposure")
def telemetry_exposure() -> Dict[str, Any]:
    if is_mock():
        return {"gross": 0.0, "net": 0.0, "long_exposure": 0.0, "short_exposure": 0.0}
    try:
        positions = reconcile.pull_positions()
    except Exception as exc:  # pragma: no cover - network path
        raise HTTPException(502, f"Positions fetch failed: {exc}") from exc

    long_exposure = 0.0
    short_exposure = 0.0
    for pos in positions:
        market_value = float(pos.get("market_value") or 0.0)
        if market_value >= 0:
            long_exposure += market_value
        else:
            short_exposure += market_value

    gross = long_exposure + abs(short_exposure)
    net = long_exposure + short_exposure
    return {
        "gross": gross,
        "net": net,
        "long_exposure": long_exposure,
        "short_exposure": short_exposure,
    }
@app.post("/live/start")
def live_start(req: StartReq | None = None):
    if os.getenv("LIVE_TRADING","false").lower() not in ("1","true","yes"):
        raise HTTPException(403,"LIVE_TRADING env not enabled")
    preset = req.preset if req else None
    return _start_trading("live", preset)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", "8000"))
    print(f"\n=== Gigatrader API starting on 127.0.0.1:{port} ===")
    uvicorn.run("backend.api:app", host="127.0.0.1", port=port, reload=False)
