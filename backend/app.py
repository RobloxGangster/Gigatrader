import os, sys, asyncio, threading, subprocess
from pathlib import Path
from typing import Optional, Callable, Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# --- Ensure repo root is importable (so "app.cli" resolves) ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Load .env (so ALPACA_* vars exist for this process) ---
try:
    from dotenv import load_dotenv, find_dotenv
    _env_path = find_dotenv(str(ROOT / ".env"), usecwd=True)
    if _env_path:
        load_dotenv(_env_path, override=False)
except Exception:
    # dotenv is optional; if missing we'll rely on shell env
    pass

# ---------- Alpaca helpers ----------
def _get_trading_client():
    from alpaca.trading.client import TradingClient
    key = os.environ.get("ALPACA_API_KEY_ID")
    sec = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY")
    return TradingClient(api_key=key, secret_key=sec, paper=True)

def _safe_dump(obj: Any):
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

app = FastAPI()

def start_background_runner(profile: str = "paper"):
    global runner_task, runner_loop, runner_last_error
    # reset last error
    runner_last_error = None
    if runner_task and not runner_task.done():
        return

    def _run():
        global runner_loop, runner_task, runner_last_error
        runner_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(runner_loop)
        try:
            # this import now works because ROOT is on sys.path and app/ is a package
            from app.cli import run as run_cli
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
    return {"ok": True}

@app.get("/status", response_model=StatusResp)
def status():
    return StatusResp(
        profile="live" if os.environ.get("LIVE_TRADING", "false").lower() == "true" else "paper",
        mode="running" if runner_task and not runner_task.done() else "stopped",
        market_open=False,
        preset=os.environ.get("RISK_PROFILE", "balanced"),
        last_error=runner_last_error,
    )


@app.get("/sentiment")
def sentiment(symbol: str):
    """
    Stub sentiment endpoint so diagnostics are green.
    Returns neutral score and an explanatory note.
    Replace later with real fetch & scoring (e.g., Alpaca news + lightweight polarity).
    """
    return {
        "symbol": symbol.upper(),
        "score": None,
        "sources": [],
        "note": "Sentiment not wired yet; this stub exists so diagnostics can verify the endpoint.",
    }

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
    if runner_last_error:
        return JSONResponse(status_code=500, content={"error": runner_last_error})
    return StartResp(run_id="paper-1")


@app.get("/paper/start")
def paper_start_help():
    return JSONResponse(status_code=405, content={
        "error": "Method Not Allowed",
        "hint": "Use POST /paper/start (e.g., curl -X POST http://127.0.0.1:8000/paper/start?preset=balanced)",
    })

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

# ---------- Data endpoints (robust, no 500 on missing keys) ----------
@app.get("/orders")
def orders():
    try:
        tc = _get_trading_client()
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"orders init failed: {e}"})
    try:
        data = tc.get_orders()
        return [_safe_dump(o) for o in data]
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"orders query failed: {e}"})

@app.get("/positions")
def positions():
    try:
        tc = _get_trading_client()
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"positions init failed: {e}"})
    try:
        data = tc.get_all_positions()
        return [_safe_dump(p) for p in data]
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"positions query failed: {e}"})

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
