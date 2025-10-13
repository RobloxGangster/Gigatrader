import os, asyncio, threading, subprocess, sys
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import Optional, Callable, Any
import uvicorn

# --- NEW: direct Alpaca client helper (do not depend on app.alpaca_client) ---
def _get_trading_client():
    """Create a paper TradingClient using env credentials."""
    from alpaca.trading.client import TradingClient
    key = os.environ.get("ALPACA_API_KEY_ID")
    sec = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY in environment")
    # Always paper for safety
    return TradingClient(api_key=key, secret_key=sec, paper=True)


def _safe_dump(obj: Any):
    """Serialize Alpaca objects without assuming Pydantic version."""
    # Pydantic v2: model_dump; v1: dict; fallback: public attrs
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

# --- Runner plumbing unchanged ---
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

try:
    from services.sentiment.poller import compute_sentiment
except Exception:  # pragma: no cover - optional dependency wiring
    compute_sentiment = None

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

    threading.Thread(target=_run, daemon=True).start()


# --- NEW: health endpoint
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status", response_model=StatusResp)
def status():
    return StatusResp(
        profile=os.environ.get("LIVE_TRADING", "false") == "true" and "live" or "paper",
        mode="running" if runner_task and not runner_task.done() else "stopped",
        market_open=False,
        preset=os.environ.get("RISK_PROFILE", "balanced"),
    )

@app.post("/paper/start", response_model=StartResp)
def paper_start(preset: Optional[str] = None):
    # Clear any prior kill-switch so the runner can actually start
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

@app.get("/orders")
def orders():
    tc = _get_trading_client()
    try:
        data = tc.get_orders()
        return [_safe_dump(o) for o in data]
    except Exception as e:
        return {"error": f"orders failed: {e}"}

@app.get("/positions")
def positions():
    tc = _get_trading_client()
    try:
        data = tc.get_all_positions()
        return [_safe_dump(p) for p in data]
    except Exception as e:
        return {"error": f"positions failed: {e}"}


@app.get("/sentiment")
def sentiment(symbol: str = Query(..., min_length=1, max_length=10)):
    if not compute_sentiment:
        return {"error": "sentiment not available"}
    result = compute_sentiment(symbol)

    score_value = None
    features = {}

    if isinstance(result, tuple):
        if result:
            score_value = result[0]
        if len(result) > 1 and isinstance(result[1], dict):
            features = result[1]
    elif isinstance(result, dict):
        score_value = result.get("score")
        features = result.get("features", {}) or {}
    elif hasattr(result, "score"):
        score_value = getattr(result, "score")
        maybe_features = getattr(result, "features", {})
        if isinstance(maybe_features, dict):
            features = maybe_features
    else:
        score_value = result

    score = float(score_value if score_value is not None else 0.0)
    if not isinstance(features, dict):
        try:
            features = dict(features)
        except Exception:
            features = {}

    return {"symbol": symbol.upper(), "score": score, "features": features}

if __name__ == "__main__":
    # Honor SERVICE_PORT, but treat 0/invalid as 8000
    try:
        port = int(os.environ.get("SERVICE_PORT", "8000"))
    except Exception:
        port = 8000
    if port <= 0 or port > 65535:
        port = 8000
    uvicorn.run(app, host="127.0.0.1", port=port)
