# --- import bootstrap: ensure repo root first on sys.path ---
import sys, pathlib, os
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONPATH", str(ROOT))
# ------------------------------------------------------------

import asyncio
import threading
import subprocess
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Tuple, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from app.execution.alpaca_adapter import AlpacaAdapter

from app.execution.router import ExecIntent, OrderRouter
from app.risk import RiskManager
from app.state import ExecutionState
from core.config import alpaca_config_ok, get_alpaca_settings
from core.kill_switch import KillSwitch

from dotenv import load_dotenv

load_dotenv(override=False)

_kill_switch = KillSwitch()

_SENT_CACHE: Dict[Tuple[str, int, int], Tuple[float, Dict[str, Any]]] = {}
_SENT_TTL_SEC = 300  # 5 minutes

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
    # UI-required top-level fields
    run_id: str
    daily_loss_pct: float            # fraction of equity lost today [0..1]
    max_exposure: float              # portfolio notional cap (e.g., MAX_NOTIONAL)
    open_positions: int
    breached: bool                   # true if any hard risk breach or kill switch

    # Existing/aux fields
    profile: str
    equity: float
    cash: float
    exposure_pct: float
    day_pnl: float
    leverage: float
    kill_switch: bool
    limits: RiskLimits
    timestamp: str


log = logging.getLogger("backend")

class _UnconfiguredAlpacaAdapter:
    def __init__(self, message: str = "alpaca_unconfigured") -> None:
        self._message = message

    def __getattr__(self, _: str) -> Any:
        raise RuntimeError(self._message)


_execution_state = ExecutionState()

try:
    _broker = AlpacaAdapter()
except RuntimeError as exc:
    if "alpaca_unconfigured" in str(exc):
        log.warning("alpaca adapter unavailable: credentials missing; broker calls disabled")
        _broker = _UnconfiguredAlpacaAdapter(str(exc))
    else:
        raise

_risk_manager = RiskManager(_execution_state, kill_switch=_kill_switch)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.execution = _execution_state
    app.state.state = _execution_state
    app.state.risk = _risk_manager
    app.state.broker = _broker

    stop_flag = False

    async def recon_loop() -> None:
        nonlocal stop_flag
        broker = _broker
        backoff = 2.0
        max_backoff = 60.0
        warned_unconfigured = False
        while not stop_flag:
            try:
                open_orders = broker.get_open_orders()  # may raise RuntimeError("alpaca_unauthorized")
                positions = broker.get_positions()
                account = broker.get_account()
                _execution_state.update_orders(open_orders)
                _execution_state.update_positions(positions)
                _execution_state.update_account(account)
                backoff = 2.0
                warned_unconfigured = False
            except RuntimeError as re:
                msg = str(re)
                if msg == "alpaca_unauthorized":
                    log.warning(
                        "reconcile paused: alpaca unauthorized. Check credentials. Backing off %.0fs",
                        backoff,
                    )
                elif "alpaca_unconfigured" in msg:
                    if not warned_unconfigured:
                        log.warning(
                            "reconcile paused: alpaca not configured. Set ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY.",
                        )
                        warned_unconfigured = True
                else:
                    log.warning("reconcile runtime error: %s", re)
            except Exception as exc:  # noqa: BLE001
                log.error("reconcile error (%s): %s", exc.__class__.__name__, exc)
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 1.7)

    task = asyncio.create_task(recon_loop())
    try:
        yield
    finally:
        stop_flag = True
        task.cancel()
        try:
            await task
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)

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
    try:
        return _kill_switch.engaged_sync()
    except Exception:
        return os.path.exists(".kill_switch")


def _read_run_id() -> str:
    """Try to read current run id from a file set by paper runner; else 'idle'."""
    p = Path(".run_id")
    if p.exists():
        try:
            s = p.read_text(encoding="utf-8").strip()
            if s:
                return s
        except Exception:
            pass
    return "idle"


def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name)
        return float(v) if v not in (None, "", "None") else default
    except Exception:
        return default


@app.get("/risk", response_model=RiskSnapshot)
def get_risk():
    """
    Return current risk snapshot from Alpaca (if keys present) + local settings.
    Always returns 200 with safe defaults so the UI can render.
    """
    profile = os.environ.get("RISK_PROFILE", "balanced")
    limits = RiskLimits(
        max_position_pct=_env_float("RISK_MAX_POSITION_PCT", 0.2),
        max_leverage=_env_float("RISK_MAX_LEVERAGE", 2.0),
        max_daily_loss_pct=_env_float("RISK_MAX_DAILY_LOSS_PCT", 0.05),
    )

    snapshot = _execution_state.account_snapshot()
    if not snapshot.get("id") and alpaca_config_ok():
        try:
            account = _broker.get_account()
            _execution_state.update_account(account)
            snapshot = _execution_state.account_snapshot()
        except Exception as exc:  # noqa: BLE001
            log.warning("risk account fetch failed: %s", exc)

    equity = float(snapshot.get("equity", 0.0) or 0.0)
    cash = float(snapshot.get("cash", 0.0) or 0.0)
    day_pnl = float(snapshot.get("day_pnl", 0.0) or 0.0)
    leverage = float(snapshot.get("multiplier", 1.0) or 1.0)
    portfolio_notional = float(_execution_state.get_portfolio_notional())
    open_positions = sum(1 for pos in _execution_state.get_positions().values() if abs(pos.qty) > 0)

    # Derived & limits from env
    daily_loss_limit_abs = _env_float("DAILY_LOSS_LIMIT", -1.0)   # absolute currency amount
    max_notional = _env_float("MAX_NOTIONAL", -1.0)

    # daily loss percent (treat gains as 0% loss)
    loss_abs = max(0.0, -float(day_pnl))
    daily_loss_pct = 0.0 if equity <= 0 else (loss_abs / max(equity, 1e-9))

    # max exposure defaults: if not set, approximate from equity * leverage
    if max_notional <= 0:
        max_exposure = (equity * max(leverage, 1.0)) or 0.0
    else:
        max_exposure = max_notional

    # breach logic: kill switch OR (configured daily loss limit exceeded)
    limit_breached = False
    if daily_loss_limit_abs is not None and daily_loss_limit_abs > 0:
        limit_breached = (loss_abs >= daily_loss_limit_abs)

    kill = _kill_switch_on()
    breached = bool(kill or limit_breached)

    return RiskSnapshot(
        run_id=_read_run_id(),
        daily_loss_pct=float(daily_loss_pct),
        max_exposure=float(max_exposure),
        open_positions=int(open_positions),
        breached=breached,

        profile=profile,
        equity=float(equity),
        cash=float(cash),
        exposure_pct=0.0 if equity <= 0 else min(1.0, portfolio_notional / max(equity, 1e-9)),
        day_pnl=float(day_pnl),
        leverage=float(leverage),
        kill_switch=kill,
        limits=limits,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
@app.get("/debug/alpaca")
def debug_alpaca():
    cfg = get_alpaca_settings()
    tail = (cfg.api_key_id[-4:] if cfg.api_key_id else None)
    return {
        "paper": cfg.paper,
        "base_url": cfg.base_url or ("paper" if cfg.paper else "live"),
        "has_key": bool(cfg.api_key_id),
        "key_tail": tail,
    }


@app.get("/alpaca/ping")
def alpaca_ping():
    try:
        acct = _broker.get_account_summary()
        return {
            "auth_ok": True,
            "status": acct.get("status"),
            "currency": acct.get("currency"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "auth_ok": False,
            "error": exc.__class__.__name__,
            "detail": str(exc),
        }


@app.get("/alpaca/account")
def alpaca_account():
    from app.execution.alpaca_adapter import AlpacaAdapter

    try:
        broker = AlpacaAdapter()
        acct = broker.get_account()
        return dict(
            id=str(getattr(acct, "id", "")),
            status=str(getattr(acct, "status", "")),
            cash=float(getattr(acct, "cash", 0) or 0),
            portfolio_value=float(getattr(acct, "portfolio_value", 0) or 0),
            pattern_day_trader=bool(getattr(acct, "pattern_day_trader", False)),
        )
    except RuntimeError as e:
        if "alpaca_unconfigured" in str(e):
            return {"error": "Alpaca client not configured"}
        raise


@app.post("/orders/test")
def orders_test(symbol: str = "AAPL", side: str = "buy", qty: int = 1, limit_price: float = 1.00):
    """Submit a sample order; generates a fresh ``client_order_id`` on every call."""

    try:
        risk = app.state.risk if hasattr(app.state, "risk") else None
        state = app.state.state if hasattr(app.state, "state") else None
        if risk is None or state is None:
            # Fallback (replace with your real builders)
            from app.risk import RiskManager
            from app.state import InMemoryState

            state = InMemoryState()
            risk = RiskManager(state)

        router = OrderRouter(risk, state)
        return router.submit(
            ExecIntent(symbol=symbol, side=side, qty=qty, limit_price=limit_price, bracket=True)
        )
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "unauthorized" in msg.lower():
            raise HTTPException(status_code=401, detail="Alpaca unauthorized: check API key/secret/base URL")
        raise HTTPException(status_code=500, detail=f"broker_error: {msg}")


@app.post("/orders/cancel_all")
def cancel_all_orders():
    try:
        if _broker is None:
            raise RuntimeError("alpaca_unconfigured")
        result = _broker.cancel_all_open_orders()
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    try:
        if _broker is None:
            raise RuntimeError("alpaca_unconfigured")
        return _broker.cancel_order(order_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

# ---------- Paper controls ----------
@app.post("/paper/start", response_model=StartResp)
def paper_start(preset: Optional[str] = None):
    try:
        _kill_switch.reset_sync()
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
    _kill_switch.engage_sync()
    return {"ok": True}

@app.post("/paper/flatten")
def paper_flatten():
    _kill_switch.engage_sync()
    try:
        subprocess.check_call([sys.executable, "backend/tools/flatten_all.py"])
    except Exception:
        pass
    return {"ok": True}

# ---------- Data endpoints ----------
@app.get("/orders")
def orders():
    if alpaca_config_ok():
        try:
            open_orders = _broker.get_open_orders()
            _execution_state.update_orders(open_orders)
        except Exception as exc:  # noqa: BLE001
            log.warning("orders fetch failed: %s", exc)
    return _execution_state.orders_snapshot()


@app.get("/positions")
def positions():
    if alpaca_config_ok():
        try:
            current_positions = _broker.get_positions()
            _execution_state.update_positions(current_positions)
        except Exception as exc:  # noqa: BLE001
            log.warning("positions fetch failed: %s", exc)
    return _execution_state.positions_snapshot()

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

