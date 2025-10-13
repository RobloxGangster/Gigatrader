import os, sys, asyncio, threading, subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Any, Tuple, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

_SENT_CACHE: Dict[Tuple[str, int, int], Tuple[float, Dict[str, Any]]] = {}
_SENT_TTL_SEC = 300  # 5 minutes

# ---------- Path + .env ----------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv, find_dotenv
    _env = find_dotenv(str(ROOT / ".env"), usecwd=True)
    if _env:
        load_dotenv(_env, override=False)
except Exception:
    pass

# ---------- Robust runner import ----------
import importlib.util
def _import_runner():
    """
    Load app.cli:run even if a top-level module named 'app' shadows the package.
    """
    # If 'app' is a module (file), drop it so we can import the package namespace
    if "app" in sys.modules and not hasattr(sys.modules["app"], "__path__"):
        del sys.modules["app"]

    # Try normal package import
    try:
        from app.cli import run as run_cli
        return run_cli
    except Exception:
        pass

    # Fallback to direct file import
    cand = ROOT / "app" / "cli.py"
    if cand.exists():
        spec = importlib.util.spec_from_file_location("gt_runner.cli", cand)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        if hasattr(mod, "run"):
            return getattr(mod, "run")

    # Last-resort: scan for app/cli.py anywhere under repo
    for p in ROOT.rglob("cli.py"):
        if p.parent.name == "app":
            spec = importlib.util.spec_from_file_location("gt_runner.cli", p)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(mod)
            if hasattr(mod, "run"):
                return getattr(mod, "run")

    raise ImportError("Could not locate app.cli:run")

# ---------- Alpaca helpers (orders/positions) ----------
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

class RiskLimits(BaseModel):
    max_position_pct: float = 0.2
    max_leverage: float = 2.0
    max_daily_loss_pct: float = 0.05

class RiskSnapshot(BaseModel):
    profile: str
    equity: float
    cash: float
    exposure_pct: float
    day_pnl: float
    leverage: float
    kill_switch: bool
    limits: RiskLimits
    timestamp: str

app = FastAPI()

def start_background_runner(profile: str = "paper"):
    global runner_task, runner_loop, runner_last_error
    runner_last_error = None
    if runner_task and not runner_task.done():
        return

    def _run():
        global runner_loop, runner_task, runner_last_error
        runner_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(runner_loop)
        try:
            run_cli = _import_runner()
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

def _kill_switch_on() -> bool:
    return os.path.exists(".kill_switch")

@app.get("/risk", response_model=RiskSnapshot)
def get_risk():
    """
    Return current risk snapshot derived from Alpaca account + local controls.
    - Uses TradingClient (paper) to read equity/cash/day pnl/leverage.
    - Limits come from env (optional) or sensible defaults.
    - kill_switch reflects presence of .kill_switch file.
    """
    limits = RiskLimits(
        max_position_pct=float(os.environ.get("RISK_MAX_POSITION_PCT", 0.2)),
        max_leverage=float(os.environ.get("RISK_MAX_LEVERAGE", 2.0)),
        max_daily_loss_pct=float(os.environ.get("RISK_MAX_DAILY_LOSS_PCT", 0.05)),
    )
    profile = os.environ.get("RISK_PROFILE", "balanced")

    try:
        tc = _get_trading_client()
        acct = tc.get_account()

        def to_float(value: Any) -> float:
            if hasattr(value, "model_dump"):
                try:
                    dumped = value.model_dump()
                    if isinstance(dumped, dict):
                        return float(dumped.get("amount", dumped))
                except Exception:
                    pass
            try:
                return float(value)
            except Exception:
                return 0.0

        equity = to_float(getattr(acct, "equity", 0.0))
        cash = to_float(getattr(acct, "cash", 0.0))
        day_pnl = to_float(getattr(acct, "daytrading_buying_power", 0.0)) * 0.0
        try:
            day_pnl = float(getattr(acct, "daytrading_buying_power", 0.0)) * 0.0
            if hasattr(acct, "daytrade_count"):
                _ = acct.daytrade_count
        except Exception:
            pass
        try:
            day_pnl = float(getattr(acct, "day_pl", day_pnl))
        except Exception:
            pass
        try:
            leverage = float(getattr(acct, "multiplier", 1.0))
        except Exception:
            leverage = 1.0
    except Exception:
        equity, cash, day_pnl, leverage = 0.0, 0.0, 0.0, 1.0

    exposure_pct = 0.0 if equity == 0 else max(0.0, min(1.0, (equity - cash) / max(equity, 1e-9)))

    return RiskSnapshot(
        profile=profile,
        equity=float(equity),
        cash=float(cash),
        exposure_pct=float(exposure_pct),
        day_pnl=float(day_pnl),
        leverage=float(leverage),
        kill_switch=_kill_switch_on(),
        limits=limits,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

# ---------- Paper controls ----------
@app.post("/paper/start", response_model=StartResp)
def paper_start(preset: Optional[str] = None):
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
        "hint": "Use POST /paper/start (e.g., curl -X POST http://127.0.0.1:8000/paper/start?preset=balanced)"
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

# ---------- Data endpoints ----------
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

# ---------- NEW: Real sentiment via Alpaca News (with graceful fallback) ----------
@app.get("/sentiment")
def sentiment(symbol: str, hours_back: int = 24, limit: int = 50):
    """
    Compute a simple sentiment score from recent Alpaca news headlines ([-1,1]).
    Returns 200 with real scores or a neutral fallback + reason.
    Caches per (symbol,hours_back,limit) for 5 minutes.
    """
    key = (symbol.upper(), int(hours_back), int(limit))
    now = time.time()
    cached = _SENT_CACHE.get(key)
    if cached:
        ts, payload = cached
        if (now - ts) < _SENT_TTL_SEC:
            payload = dict(payload)  # shallow copy
            payload["cached"] = True
            return payload

    try:
        from services.sentiment.fetchers import AlpacaNewsFetcher
        from services.sentiment.scoring import heuristic_score
    except Exception as e:
        payload = {
            "symbol": symbol.upper(),
            "score": None,
            "items": [],
            "note": f"Sentiment modules not available: {e}"
        }
        _SENT_CACHE[key] = (now, payload)
        return payload

    try:
        fetcher = AlpacaNewsFetcher()
        items = fetcher.fetch_headlines(symbol.upper(), hours_back=hours_back, limit=limit)
        if not items:
            payload = {"symbol": symbol.upper(), "score": 0.0, "items": [], "note": "No news found"}
            _SENT_CACHE[key] = (now, payload)
            return payload
        scores = [heuristic_score(i.get("headline",""), i.get("summary","")) for i in items]
        score = sum(scores)/len(scores)
        payload = {"symbol": symbol.upper(), "score": round(score, 4), "count": len(items), "items": items[:10]}
        _SENT_CACHE[key] = (now, payload)
        return payload
    except Exception as e:
        payload = {"symbol": symbol.upper(), "score": 0.0, "items": [], "note": f"Fallback: {e}"}
        _SENT_CACHE[key] = (now, payload)
        return payload

# ---------- Entrypoint ----------
if __name__ == "__main__":
    try:
        port = int(os.environ.get("SERVICE_PORT", "8000"))
    except Exception:
        port = 8000
    if port <= 0 or port > 65535:
        port = 8000
    uvicorn.run(app, host="127.0.0.1", port=port)
