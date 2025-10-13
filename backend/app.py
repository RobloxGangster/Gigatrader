import os, asyncio, threading, subprocess, sys
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Callable, Any
import uvicorn

# ---------- Alpaca helpers (no dependence on app.alpaca_client) ----------
def _get_trading_client():
    from alpaca.trading.client import TradingClient
    key = os.environ.get("ALPACA_API_KEY_ID")
    sec = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY in environment")
    # Always paper for safety
    return TradingClient(api_key=key, secret_key=sec, paper=True)

def _safe_dump(obj: Any):
    # Pydantic v2 -> model_dump; v1 -> dict; else fallback to vars
    for attr in ("model_dump", "dict"):
        fn: Optional[Callable] = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    try:
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    except Exception:
        return str(obj)

# ---------- Runner plumbing (unchanged) ----------
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
        from app.cli import run as run_cli  # reuse existing runner entrypoint
        runner_task = runner_loop.create_task(run_cli(async_mode=True, profile=profile))
        runner_loop.run_until_complete(runner_task)

    threading.Thread(target=_run, daemon=True).start()

# ---------- Health & status ----------
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/status", response_model=StatusResp)
def status():
    return StatusResp(
        profile="live" if os.environ.get("LIVE_TRADING", "false").lower() == "true" else "paper",
        mode="running" if runner_task and not runner_task.done() else "stopped",
        market_open=False,
        preset=os.environ.get("RISK_PROFILE", "balanced"),
    )

# ---------- Paper controls ----------
@app.post("/paper/start", response_model=StartResp)
def paper_start(preset: Optional[str] = None):
    # Clear any previous kill-switch so the runner can start
    try:
        if os.path.exists(".kill_switch"):
            os.remove(".kill_switch")
    except Exception:
        pass
    if preset:
        os.environ["RISK_PROFILE"] = preset
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

# ---------- Data endpoints (fixed) ----------
@app.get("/orders")
def orders():
    try:
        tc = _get_trading_client()
        data = tc.get_orders()
        return [_safe_dump(o) for o in data]
    except Exception as e:
        return {"error": f"orders failed: {e}"}

@app.get("/positions")
def positions():
    try:
        tc = _get_trading_client()
        data = tc.get_all_positions()
        return [_safe_dump(p) for p in data]
    except Exception as e:
        return {"error": f"positions failed: {e}"}

# ---------- Entrypoint ----------
if __name__ == "__main__":
    # Honor SERVICE_PORT; invalid/0 -> 8000
    try:
        port = int(os.environ.get("SERVICE_PORT", "8000"))
    except Exception:
        port = 8000
    if port <= 0 or port > 65535:
        port = 8000
    uvicorn.run(app, host="127.0.0.1", port=port)

