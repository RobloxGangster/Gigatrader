import asyncio
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.kill_switch import KillSwitch

load_dotenv()

app = FastAPI(title="Gigatrader API")

from backend.routes import backtests_compat  # noqa: E402
from backend.routes import options as options_routes  # noqa: E402
from backend.routes import logs as logs_routes  # noqa: E402
from backend.routes import backtest_v2 as backtest_v2_routes  # noqa: E402
from backend.routes import ml as ml_routes  # noqa: E402
from backend.routes import ml_calibration as ml_calibration_routes  # noqa: E402
from backend.routes import alpaca_live as alpaca_live_routes  # noqa: E402
from backend.routes import health as health_routes  # noqa: E402

app.include_router(ml_routes.router)
app.include_router(ml_calibration_routes.router)
app.include_router(backtest_v2_routes.router)
app.include_router(backtests_compat.router)
app.include_router(options_routes.router)
app.include_router(logs_routes.router)
app.include_router(alpaca_live_routes.router)
app.include_router(health_routes.router)


@app.on_event("startup")
async def _startup_reconcile():
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


class StartReq(BaseModel):
    preset: str | None = None


def _run_runner():
    global _running
    try:
        from services.runtime import runner as R
        R.main()
    finally:
        _running = False


@app.get("/status")
def status():
    return {
        "running": _running,
        "profile": _profile,
        "paper": os.getenv("TRADING_MODE","paper")=="paper",
        "halted": _kill_switch.engaged_sync(),
    }


@app.post("/paper/start")
def paper_start(req: StartReq | None = None):
    global _runner_thread, _running, _profile
    if _running: return {"run_id":"active"}
    os.environ["TRADING_MODE"]="paper"
    os.environ["ALPACA_PAPER"]="true"
    _profile = "paper"
    _running = True
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id":"paper"}


@app.post("/paper/stop")
def paper_stop():
    global _running
    _running = False
    _kill_switch.engage_sync()
    return {"ok": True}


@app.post("/paper/flatten")
def flatten_and_halt():
    _kill_switch.engage_sync()
    return {"ok": True, "halted": True}


@app.post("/live/start")
def live_start(req: StartReq | None = None):
    if os.getenv("LIVE_TRADING","false").lower() not in ("1","true","yes"):
        raise HTTPException(403,"LIVE_TRADING env not enabled")
    global _runner_thread, _running, _profile
    if _running: return {"run_id":"active"}
    os.environ["TRADING_MODE"]="live"
    os.environ["ALPACA_PAPER"]="false"
    _profile = "live"
    _running = True
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id":"live"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", "8000"))
    print(f"\n=== Gigatrader API starting on 127.0.0.1:{port} ===")
    uvicorn.run("backend.api:app", host="127.0.0.1", port=port, reload=False)
