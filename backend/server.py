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
from decimal import Decimal
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Tuple, Dict, Iterable, Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from app.data.market import build_data_client, bars_to_df
from app.signals.signal_engine import SignalEngine
from app.backtest.engine import run_trade_backtest
from app.ml.models import load_from_registry, DEFAULT_MODEL_NAME
from app.ml.trainer import latest_feature_row, train_intraday_classifier
from app.ml.features import FEATURE_LIST
from core.config import MOCK_MODE, get_signal_defaults
from app.execution.alpaca_adapter import AlpacaAdapter, AlpacaOrderError, AlpacaUnauthorized

from app.execution.router import ExecIntent, OrderRouter
from app.risk import RiskManager
from app.state import ExecutionState
from core.config import alpaca_config_ok
from core.kill_switch import KillSwitch

from dotenv import load_dotenv

load_dotenv(override=False)

_TEST_ORDERS_DEFAULT_DRY_RUN = os.getenv("TEST_ORDERS_DEFAULT_DRY_RUN", "true").lower() not in (
    "false",
    "0",
    "no",
    "off",
)

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

class BacktestRequest(BaseModel):
    symbol: str
    strategy: Literal["intraday_momo", "intraday_revert", "swing_breakout"]
    days: int = 30


class TrainRequest(BaseModel):
    symbols: list[str] | None = None





log = logging.getLogger("backend")

try:
    _data_client = build_data_client(mock_mode=MOCK_MODE)
except Exception as exc:
    logging.getLogger("backend").info("data client fallback: %s", exc)
    _data_client = build_data_client(mock_mode=True)

_signal_engine = SignalEngine(_data_client, config=get_signal_defaults())

_execution_state = ExecutionState()


_broker = AlpacaAdapter()
if not _broker.is_configured():
    log.warning("alpaca adapter unavailable: credentials missing; broker calls disabled")

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
        backoff_schedule = [2.0, 3.0, 5.0, 8.0, 10.0]
        backoff_index = 0
        while not stop_flag:
            delay = backoff_schedule[min(backoff_index, len(backoff_schedule) - 1)]
            try:
                orders = broker.fetch_orders()
                positions = broker.fetch_positions()
                account = broker.fetch_account()
            except AlpacaUnauthorized as exc:
                log.warning(
                    "reconcile paused: alpaca unauthorized. retrying in %.0fs",
                    delay,
                )
                backoff_index = min(backoff_index + 1, len(backoff_schedule) - 1)
                await asyncio.sleep(delay)
                continue
            except AlpacaOrderError as exc:
                log.warning(
                    "reconcile broker error: %s",
                    exc,
                )
                backoff_index = min(backoff_index + 1, len(backoff_schedule) - 1)
                await asyncio.sleep(delay)
                continue
            except Exception as exc:  # noqa: BLE001
                log.error("reconcile error (%s): %s", exc.__class__.__name__, exc)
                backoff_index = min(backoff_index + 1, len(backoff_schedule) - 1)
                await asyncio.sleep(delay)
                continue

            _execution_state.update_orders(orders)
            _execution_state.update_positions(positions)
            _execution_state.update_account(account)
            backoff_index = 0
            await asyncio.sleep(backoff_schedule[0])

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

def _normalize_payload(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _normalize_payload(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_payload(v) for v in obj]
    return obj





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
            account = _broker.fetch_account()
            _execution_state.update_account(account)
            snapshot = _execution_state.account_snapshot()
        except (AlpacaUnauthorized, AlpacaOrderError) as exc:
            log.warning("risk account fetch failed: %s", exc)
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
    info = _broker.debug_info()
    payload = dict(info)
    payload["configured"] = _broker.is_configured()
    return payload


@app.get("/alpaca/ping")
def alpaca_ping():
    if not _broker.is_configured():
        return {"auth_ok": False, "error": "alpaca_not_configured"}
    try:
        acct = _broker.fetch_account()
        return {
            "auth_ok": True,
            "status": acct.get("status"),
            "cash": acct.get("cash"),
        }
    except AlpacaUnauthorized:
        return {"auth_ok": False, "error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"auth_ok": False, "error": f"alpaca_error:{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"auth_ok": False, "error": str(exc)}


@app.get("/alpaca/account")
def alpaca_account():
    if not _broker.is_configured():
        return {"error": "Alpaca client not configured"}
    try:
        acct = _broker.fetch_account()
    except AlpacaUnauthorized:
        return {"error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"error": f"alpaca_error:{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {
        "equity": acct.get("equity"),
        "cash": acct.get("cash"),
        "buying_power": acct.get("buying_power"),
        "pattern_day_trader": acct.get("pattern_day_trader"),
        "daytrade_count": acct.get("daytrade_count"),
    }


@app.post("/alpaca/close_all_positions")
def alpaca_close_all_positions():
    if not _broker.is_configured():
        return {"ok": False, "error": "alpaca_not_configured"}
    try:
        _broker.close_all_positions(cancel_orders=True)
        return {"ok": True}
    except AlpacaUnauthorized:
        return {"ok": False, "error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"ok": False, "error": f"alpaca_error:{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@app.post("/orders/test")
def orders_test(
    symbol: str = "AAPL",
    side: str = "buy",
    qty: int = 1,
    limit_price: float = 1.00,
    confirm: bool = Query(default=False),
    execute: bool | None = Query(default=None, alias="execute"),
):
    """Submit a sample order; generates a fresh ``client_order_id`` on every call."""

    if execute is not None:
        confirm = execute

    dry_run = (not confirm) if _TEST_ORDERS_DEFAULT_DRY_RUN else False

    if not _broker.is_configured():
        return {
            "accepted": False,
            "reason": "broker_error:Alpaca client not configured",
            "client_order_id": None,
        }

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
        intent = ExecIntent(symbol=symbol, side=side, qty=qty, limit_price=limit_price, bracket=True)
        if dry_run:
            return router.submit(intent, dry_run=True)
        return router.submit(intent)
    except Exception as exc:  # noqa: BLE001
        log.exception("orders_test error", extra={"symbol": symbol, "error": str(exc)})
        return {
            "accepted": False,
            "reason": f"broker_error:{exc}",
            "client_order_id": None,
        }


@app.post("/orders/cancel_all")
def cancel_all_orders():
    if not _broker.is_configured():
        return {"error": "alpaca_not_configured"}
    try:
        result = _broker.cancel_all()
        return result
    except AlpacaUnauthorized:
        return {"error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"error": f"alpaca_error:{exc}"}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    if not _broker.is_configured():
        return {"error": "alpaca_not_configured"}
    try:
        result = _broker.cancel_order(order_id)
        return result
    except AlpacaUnauthorized:
        return {"error": "alpaca_unauthorized"}
    except AlpacaOrderError as exc:
        return {"error": f"alpaca_error:{exc}"}
    except Exception as exc:
        return {"error": str(exc)}

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


@app.get("/signals/preview")
def signals_preview(profile: str = "balanced", universe: str | None = Query(default=None)):
    symbols = None
    if universe:
        symbols = [sym.strip().upper() for sym in universe.split(",") if sym.strip()]
    try:
        bundle = _signal_engine.produce(profile=profile, universe=symbols)
        payload = bundle.model_dump(mode="json")
        return _normalize_payload(payload)
    except Exception as exc:  # noqa: BLE001
        log.info("signal preview failed", extra={"error": str(exc), "profile": profile})
        return {"error": str(exc)}


def _empty_backtest(note: str = "insufficient_data") -> Dict[str, Any]:
    zero_stats = {
        "cagr": 0.0,
        "sharpe": 0.0,
        "max_dd": 0.0,
        "winrate": 0.0,
        "avg_r": 0.0,
        "avg_trade": 0.0,
        "exposure": 0.0,
        "return_pct": 0.0,
    }
    return {"trades": [], "equity_curve": [], "stats": zero_stats, "note": note}


@app.post("/backtest/run")
def run_backtest(req: BacktestRequest):
    try:
        limit = max(int(req.days) * 390, _signal_engine.config.lookback)
        timeframe = _signal_engine.config.tf_intraday
        if req.strategy == "swing_breakout":
            timeframe = _signal_engine.config.tf_swing
        bars = _data_client.get_bars(req.symbol, timeframe=timeframe, limit=limit)
        df = bars_to_df(bars)
        if df.empty:
            return _empty_backtest()
        bundle = _signal_engine.produce(universe=[req.symbol])
        if req.strategy == "swing_breakout":
            candidate_filter = "swing_breakout"
        elif req.strategy == "intraday_momo":
            candidate_filter = "intraday_momentum"
        else:
            candidate_filter = "intraday_mean_reversion"
        candidate = next((c for c in bundle.candidates if c.kind == "equity" and c.meta.get("strategy") == candidate_filter), None)
        window = 120 if timeframe == _signal_engine.config.tf_intraday else min(len(df), req.days)
        trade_df = df.tail(max(window, 5))
        if candidate is None:
            entry_price = float(trade_df["close"].iloc[-1]) if not trade_df.empty else float(df["close"].iloc[-1])
            stop_price = entry_price * (0.99 if req.strategy != "intraday_revert" else 1.01)
            target_price = entry_price * (1.01 if req.strategy != "intraday_revert" else 0.99)
            try:
                fallback = run_trade_backtest(
                    trade_df,
                    entry=entry_price,
                    stop=stop_price,
                    target=target_price,
                    side="buy",
                    time_exit=window,
                )
                return {
                    "trades": _normalize_payload(fallback.trades),
                    "equity_curve": _normalize_payload(fallback.equity_curve),
                    "stats": _normalize_payload(fallback.stats),
                    "note": "fallback_backtest",
                }
            except Exception as exc:  # pragma: no cover - fallback safety
                log.info("fallback backtest failed", extra={"error": str(exc), "symbol": req.symbol})
                return _empty_backtest()
        result = run_trade_backtest(
            trade_df,
            entry=float(candidate.entry),
            stop=float(candidate.stop) if candidate.stop is not None else None,
            target=float(candidate.target) if candidate.target is not None else None,
            side=candidate.side,
            time_exit=window,
        )
        payload = {
            "trades": _normalize_payload(result.trades),
            "equity_curve": _normalize_payload(result.equity_curve),
            "stats": _normalize_payload(result.stats),
            "candidate": _normalize_payload(candidate.model_dump(mode="json")),
        }
        return payload
    except Exception as exc:  # noqa: BLE001
        log.info("backtest run failed", extra={"error": str(exc), "symbol": req.symbol})
        return _empty_backtest()


@app.get("/ml/status")
def ml_status():
    model = load_from_registry()
    if model is None:
        return {"model": None, "status": "missing"}
    created_at = model.created_at.isoformat() if model.created_at else None
    feature_importances: list[dict[str, float]] = []
    try:
        calibrated = getattr(model, "calibrated_model", None)
        base = None
        if calibrated is not None:
            base = getattr(calibrated, "base_estimator", None) or getattr(calibrated, "estimator", None)
        estimator = None
        if base is not None:
            estimator = getattr(base, "named_steps", {}).get("estimator")
        elif hasattr(calibrated, "named_steps"):
            estimator = getattr(calibrated, "named_steps", {}).get("estimator")
        if estimator is not None and hasattr(estimator, "coef_"):
            coefs = getattr(estimator, "coef_")
            if isinstance(coefs, (list, tuple)) or getattr(coefs, "ndim", 1) == 2:
                values = [abs(float(v)) for v in coefs[0]]
                feature_importances = [
                    {"feature": FEATURE_LIST[idx], "importance": values[idx]}
                    for idx in range(min(len(values), len(FEATURE_LIST)))
                ]
                feature_importances.sort(key=lambda item: item["importance"], reverse=True)
    except Exception:  # pragma: no cover - diagnostic only
        feature_importances = []
    return {"model": DEFAULT_MODEL_NAME, "created_at": created_at, "metrics": _normalize_payload(model.metrics or {}), "feature_importances": feature_importances}


@app.get("/ml/features")
def ml_features(symbol: str = Query(..., description="Ticker symbol")):
    try:
        features, meta = latest_feature_row(symbol, _data_client)
        row = features.iloc[-1].to_dict()
        return {"symbol": symbol.upper(), "features": _normalize_payload(row), "meta": _normalize_payload(meta)}
    except Exception as exc:  # noqa: BLE001
        log.info("ml features failed", extra={"error": str(exc), "symbol": symbol})
        return {"error": str(exc)}


@app.api_route("/ml/predict", methods=["GET", "POST"])
async def ml_predict(request: Request, symbol: str | None = Query(default=None, description="Ticker symbol")):
    body_symbol: str | None = None
    if request.method == "POST":
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            body_symbol = payload.get("symbol")

    symbol_param = body_symbol or symbol or request.query_params.get("symbol")
    if not symbol_param:
        return JSONResponse(status_code=400, content={"error": "symbol_required"})

    model = load_from_registry()
    if model is None:
        return {"model": None, "status": "missing"}

    try:
        features, meta = latest_feature_row(symbol_param, _data_client)
        proba = model.predict_proba(features)
        if isinstance(proba, list):
            p_up = float(proba[-1]) if proba else 0.0
        else:
            p_up = float(proba)
        return {"symbol": symbol_param.upper(), "p_up_15m": p_up, "model": DEFAULT_MODEL_NAME}
    except Exception as exc:  # noqa: BLE001
        log.info("ml predict failed", extra={"error": str(exc), "symbol": symbol_param})
        return {"error": str(exc)}


@app.post("/ml/train")
def ml_train(payload: TrainRequest | None = None):
    symbols = payload.symbols if payload and payload.symbols else _signal_engine.config.universe[:2]
    try:
        metrics = train_intraday_classifier(symbols, _data_client)
        return {"model": DEFAULT_MODEL_NAME, "metrics": _normalize_payload(metrics)}
    except Exception as exc:  # noqa: BLE001
        log.info("ml train failed", extra={"error": str(exc), "symbols": symbols})
        return {"error": str(exc)}


# ---------- Data endpoints ----------
@app.get("/orders")
def orders():
    if _broker.is_configured():
        try:
            open_orders = _broker.fetch_orders()
            _execution_state.update_orders(open_orders)
        except AlpacaUnauthorized:
            log.warning("orders fetch paused: alpaca unauthorized")
        except AlpacaOrderError as exc:
            log.warning("orders fetch failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("orders fetch failed: %s", exc)
    return _execution_state.orders_snapshot()


@app.get("/positions")
def positions():
    if _broker.is_configured():
        try:
            current_positions = _broker.fetch_positions()
            _execution_state.update_positions(current_positions)
        except AlpacaUnauthorized:
            log.warning("positions fetch paused: alpaca unauthorized")
        except AlpacaOrderError as exc:
            log.warning("positions fetch failed: %s", exc)
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

