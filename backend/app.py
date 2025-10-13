import os, asyncio, threading, subprocess, sys
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn

runner_task = None
runner_loop = None

class StartResp(BaseModel):
    run_id: str

class StatusResp(BaseModel):
    profile: str
    mode: str
    market_open: bool
    preset: Optional[str] = None

app = FastAPI()

def start_background_runner(profile: str = "paper"):
    global runner_task, runner_loop
    if runner_task and not runner_task.done():
        return

    def _run():
        global runner_loop, runner_task
        runner_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(runner_loop)
        from app.cli import run as run_cli
        runner_task = runner_loop.create_task(run_cli(async_mode=True, profile=profile))
        runner_loop.run_until_complete(runner_task)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

@app.get("/status", response_model=StatusResp)
def status():
    return StatusResp(
        profile=os.environ.get("LIVE_TRADING", "false") == "true" and "live" or "paper",
        mode="running" if runner_task else "stopped",
        market_open=False,
        preset=os.environ.get("RISK_PROFILE", "balanced"),
    )

@app.post("/paper/start", response_model=StartResp)
def paper_start(preset: Optional[str] = None):
    os.environ["RISK_PROFILE"] = preset or os.environ.get("RISK_PROFILE", "balanced")
    start_background_runner(profile="paper")
    return StartResp(run_id="paper-1")

@app.post("/paper/stop")
def paper_stop():
    open(".kill_switch", "w").close()
    return {"ok": True}

@app.post("/paper/flatten")
def paper_flatten():
    open(".kill_switch", "w").close()
    try:
        subprocess.check_call([sys.executable, "backend/tools/flatten_all.py"])
    except Exception:
        pass
    return {"ok": True}

@app.get("/orders")
def orders():
    from app.alpaca_client import get_trading_client
    tc = get_trading_client(paper=True)
    return [getattr(o, "__dict__", dict(o)) for o in tc.get_orders()]

@app.get("/positions")
def positions():
    from app.alpaca_client import get_trading_client
    tc = get_trading_client(paper=True)
    return [getattr(p, "__dict__", dict(p)) for p in tc.get_all_positions()]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
