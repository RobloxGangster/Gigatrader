"""Asynchronous trading loop orchestrating signal, ML, risk and execution."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
import inspect
import math
import threading

from app.execution.router import ExecIntent, OrderRouter
from app.risk import Proposal, RiskManager
from app.signals.signal_engine import SignalBundle, SignalCandidate
from core.config import MOCK_MODE, TradeLoopConfig

log = logging.getLogger(__name__)

DUP_KEYS = ("duplicate_client_order_id", "duplicate client", "duplicate_client")


def _is_duplicate_coid(reason: str | None) -> bool:
    if not reason:
        return False
    r = reason.lower()
    return any(marker in r for marker in DUP_KEYS) or "duplicate coid" in r or "duplicate" in r


def _now_ts() -> float:
    return time.time()


def _uppercase(symbol: str) -> str:
    return symbol.upper() if symbol else symbol


def _dig(obj: Any, path: str) -> Any:
    parts = path.split(".")
    cur = obj
    for p in parts:
        try:
            if isinstance(cur, dict):
                cur = cur.get(p, None)
            elif is_dataclass(cur):
                cur = asdict(cur).get(p, None)
            elif hasattr(cur, "model_dump"):
                d = cur.model_dump()
                cur = d.get(p, None) if isinstance(d, dict) else getattr(cur, p, None)
            else:
                cur = getattr(cur, p)
        except Exception:
            return None
        if cur is None:
            return None
    return cur


def _get_num(obj: Any, paths: Iterable[str], default: float = float("nan")) -> float:
    """Try multiple (possibly dotted) paths; return float or default."""
    for p in paths:
        v = _dig(obj, p)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return default


def _ev_and_secondary(cand: Any) -> tuple[float, float]:
    ev = _get_num(
        cand,
        (
            "ev",
            "expected_value",
            "metrics.ev",
            "metrics.expected_value",
            "scores.ev",
            "scores.expected_value",
            "score",
            "alpha",
            "policy_score",
        ),
        default=float("nan"),
    )
    if ev is None or (isinstance(ev, float) and math.isnan(ev)):
        ev = 0.0

    secondary = _get_num(
        cand,
        (
            "p_win",
            "prob",
            "score",
            "alpha",
            "policy_score",
            "metrics.score",
            "scores.alpha",
            "scores.policy_score",
        ),
        default=0.0,
    )
    return float(ev), float(secondary)


def _get_str(obj: Any, paths: Iterable[str], default: str = "") -> str:
    for p in paths:
        v = _dig(obj, p)
        if v is None:
            continue
        try:
            return str(v)
        except Exception:
            continue
    return default


def _get_ts(obj: Any) -> float:
    for p in ("ts", "timestamp", "event_time", "created_at", "meta.ts", "meta.timestamp"):
        v = _dig(obj, p)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, datetime):
            return v.timestamp()
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
    return 0.0


def _score_tuple(cand: Any) -> tuple:
    """
    Primary: EV (desc) from a wide set of names, even nested.
    Secondary: win/alpha/policy scores (desc).
    Ties: symbol asc, then timestamp asc (stable).
    """

    ev, secondary = _ev_and_secondary(cand)

    sym = _get_str(cand, ("symbol", "underlying", "ticker", "meta.symbol"), default="")
    ts = _get_ts(cand)

    # sort asc -> negate numeric keys to get desc
    return (-float(ev), -float(secondary), sym, float(ts))


@dataclass
class _RankPayload:
    base: Any
    ev: float
    expected_value: float
    score: float | None
    alpha: float | None
    policy_score: float | None
    p_win: float | None
    symbol: str
    timestamp: Any
    ts: Any
    event_time: Any
    created_at: Any

    def model_dump(self) -> dict[str, Any]:
        if hasattr(self.base, "model_dump"):
            try:
                data = self.base.model_dump()
                if isinstance(data, dict):
                    return data
            except Exception:  # pragma: no cover - defensive
                pass
        return {}


def _build_rank_payload(candidate: Any, expected_value: float, direction_prob: float | None) -> _RankPayload:
    meta: Mapping[str, Any] | None = getattr(candidate, "meta", None)
    meta_dict: Mapping[str, Any] = meta if isinstance(meta, Mapping) else {}

    def _meta_or_attr(name: str) -> Any:
        if name in meta_dict and meta_dict[name] is not None:
            return meta_dict[name]
        if isinstance(candidate, dict):
            return candidate.get(name)
        return getattr(candidate, name, None)

    return _RankPayload(
        base=candidate,
        ev=float(expected_value),
        expected_value=float(expected_value),
        score=_meta_or_attr("score"),
        alpha=_meta_or_attr("alpha"),
        policy_score=_meta_or_attr("policy_score"),
        p_win=direction_prob if direction_prob is not None else _meta_or_attr("p_win"),
        symbol=str(_meta_or_attr("symbol") or getattr(candidate, "symbol", "") or ""),
        timestamp=_meta_or_attr("timestamp"),
        ts=_meta_or_attr("ts"),
        event_time=_meta_or_attr("event_time"),
        created_at=_meta_or_attr("created_at"),
    )


class TradeOrchestrator:
    """Coordinates the end-to-end live trading decision loop."""

    def __init__(
        self,
        *,
        data_client: Any,
        signal_generator: Any,
        ml_predictor: Any | None,
        risk_manager: RiskManager,
        router: OrderRouter,
        config: TradeLoopConfig | None = None,
    ) -> None:
        self.data_client = data_client
        self.signal_generator = signal_generator
        self.ml_predictor = ml_predictor
        self.risk_manager = risk_manager
        self.router = router
        self._base_config = config or TradeLoopConfig()
        self._config = self._base_config
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._metrics_lock = threading.Lock()
        self._metrics = {"queued": 0, "considered": 0, "routed": 0, "accepted": 0}
        self._last_decisions: deque[dict[str, Any]] = deque(maxlen=50)
        self._last_error: str | None = None
        self._last_run: float | None = None
        self._last_universe: list[str] = list(self._config.universe)
        self._broker_disabled = False
        self._mock_routing = self._infer_mock_mode()

    async def start(self, overrides: Mapping[str, Any] | None = None) -> TradeLoopConfig:
        """Start the trading loop, applying optional config overrides."""

        async with self._state_lock:
            self._config = self._config.with_overrides(**(overrides or {}))
            self._mock_routing = self._infer_mock_mode()
            if self._task and not self._task.done():
                return self._config

            self._stop_event = asyncio.Event()
            self._reset_metrics()
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run_loop())
            return self._config

    async def stop(self) -> None:
        """Request the loop to stop and wait for completion."""

        async with self._state_lock:
            task = self._task
            if not task:
                return
            self._stop_event.set()

        try:
            await task
        finally:
            async with self._state_lock:
                self._task = None
                self._stop_event = asyncio.Event()

    def status(self) -> dict[str, Any]:
        """Return the latest status snapshot."""

        running = bool(self._task and not self._task.done())
        with self._metrics_lock:
            metrics = dict(self._metrics)
        last_run_iso: str | None = None
        if self._last_run is not None:
            last_run_iso = datetime.fromtimestamp(self._last_run, timezone.utc).isoformat()
        return {
            "running": running,
            "profile": self._config.profile,
            "universe": list(self._last_universe),
            "interval_sec": float(self._config.interval_sec),
            "top_n": int(self._config.top_n),
            "min_conf": float(self._config.min_conf),
            "min_ev": float(self._config.min_ev),
            "metrics": metrics,
            "broker": {
                "mock_mode": self._mock_routing,
                "disabled": self._broker_disabled,
            },
            "last_error": self._last_error,
            "last_run": last_run_iso,
        }

    def resolved_config(self) -> dict[str, Any]:
        return self._config.to_dict()

    def last_decisions(self) -> list[dict[str, Any]]:
        return list(self._last_decisions)

    async def _run_loop(self) -> None:
        log.info("trade loop started", extra={"interval": self._config.interval_sec})
        try:
            while not self._stop_event.is_set():
                await self._cycle_once()
                wait_time = max(float(self._config.interval_sec), 0.0)
                if wait_time <= 0:
                    await asyncio.sleep(0)
                    continue
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            log.exception("trade loop crashed", extra={"error": str(exc)})
            self._last_error = str(exc)
        finally:
            log.info("trade loop stopped")

    async def _cycle_once(self) -> None:
        started = _now_ts()
        config = self._config
        try:
            bundle: SignalBundle = self.signal_generator.produce(
                profile=config.profile,
                universe=config.universe,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("signal production failed", extra={"error": str(exc)})
            self._record_decision(
                {
                    "symbol": "*",
                    "side": "neutral",
                    "confidence": 0.0,
                    "expected_value": 0.0,
                    "qty": 0,
                    "filters": ["signal_error"],
                    "status": "error",
                    "reason": str(exc),
                }
            )
            self._last_error = str(exc)
            await asyncio.sleep(0)
            return

        candidates = list(bundle.candidates)
        with self._metrics_lock:
            self._metrics["queued"] += len(candidates)
        self._last_universe = list(config.universe)
        self._last_run = started

        ml_probs = self._probabilities([c.symbol for c in candidates])

        scored: list[tuple[SignalCandidate, float, float | None, _RankPayload]] = []
        skipped: list[dict[str, Any]] = []
        for candidate in candidates:
            symbol = _uppercase(candidate.symbol)
            p_up = ml_probs.get(symbol)
            direction_prob = self._direction_probability(candidate, p_up)
            expected_value = self._expected_value(candidate, direction_prob)
            filters = []
            if candidate.confidence < config.min_conf:
                filters.append("confidence_below_min")
            if expected_value < config.min_ev:
                filters.append("ev_below_min")
            record = {
                "symbol": symbol,
                "side": candidate.side,
                "confidence": float(candidate.confidence),
                "probability": direction_prob,
                "expected_value": float(expected_value),
                "qty": 0,
                "filters": filters,
                "status": "filtered" if filters else "pending",
            }
            if filters:
                skipped.append(record)
                continue
            rank_payload = _build_rank_payload(candidate, expected_value, direction_prob)
            scored.append((candidate, expected_value, direction_prob, rank_payload))

        with self._metrics_lock:
            self._metrics["considered"] += len(scored)

        if not scored:
            for record in skipped:
                self._record_decision(record)
            return

        scored.sort(key=lambda item: _score_tuple(item[3]))
        selected = scored[: config.top_n]
        dropped = scored[config.top_n :]
        for candidate, ev_value, direction_prob, _ in dropped:
            self._record_decision(
                {
                    "symbol": _uppercase(candidate.symbol),
                    "side": candidate.side,
                    "confidence": float(candidate.confidence),
                    "probability": direction_prob,
                    "expected_value": float(ev_value),
                    "qty": 0,
                    "filters": ["rank_out_of_range"],
                    "status": "skipped",
                }
            )

        for record in skipped:
            self._record_decision(record)

        for candidate, expected_value, direction_prob, _ in selected:
            await self._execute_candidate(candidate, expected_value, direction_prob)

    async def _execute_candidate(
        self,
        candidate: SignalCandidate,
        expected_value: float,
        direction_prob: float | None,
    ) -> None:
        symbol = _uppercase(candidate.symbol)
        qty = self._size_candidate(candidate)
        record = {
            "symbol": symbol,
            "side": candidate.side,
            "confidence": float(candidate.confidence),
            "probability": direction_prob,
            "expected_value": float(expected_value),
            "qty": int(qty),
            "filters": [],
            "status": "pending",
        }

        if qty <= 0:
            record["status"] = "filtered"
            record["filters"] = ["sizing_zero"]
            self._record_decision(record)
            return

        proposal = Proposal(
            symbol=symbol,
            side=candidate.side,
            qty=float(qty),
            price=float(candidate.entry),
            is_option=candidate.kind == "option",
            est_sl=float(candidate.stop) if candidate.stop is not None else None,
            est_tp=float(candidate.target) if candidate.target is not None else None,
        )

        try:
            decision = self.risk_manager.pre_trade_check(proposal)
        except Exception as exc:  # noqa: BLE001
            log.exception("risk check failed", extra={"symbol": symbol, "error": str(exc)})
            record["status"] = "error"
            record["filters"] = ["risk_error"]
            record["reason"] = str(exc)
            self._record_decision(record)
            return

        if not getattr(decision, "allow", False):
            record["status"] = "rejected"
            record["filters"] = [f"risk:{getattr(decision, 'reason', 'denied')}"]
            self._record_decision(record)
            return

        max_qty = getattr(decision, "max_qty", None)
        if max_qty is not None:
            qty = min(qty, int(max(0.0, max_qty)))
        record["qty"] = qty
        if qty <= 0:
            record["status"] = "filtered"
            record["filters"].append("risk_max_qty")
            self._record_decision(record)
            return

        policy_meta: dict[str, Any] = dict(candidate.meta or {})
        policy_meta.update(
            {
                "confidence": float(candidate.confidence),
                "expected_value": float(expected_value),
                "proba_up": direction_prob,
                "probability": direction_prob,
                "price": float(candidate.entry),
                "limit_price": float(candidate.entry),
                "stop_price": float(candidate.stop) if candidate.stop is not None else None,
                "target_price": float(candidate.target) if candidate.target is not None else None,
                "requested_qty": qty,
                "account_equity": self._account_equity_snapshot(),
            }
        )
        if policy_meta.get("alpha") is None:
            try:
                policy_meta["alpha"] = float(candidate.confidence) - 1.0
            except (TypeError, ValueError):
                policy_meta["alpha"] = 0.0
        if policy_meta.get("atr") is None and candidate.stop is not None:
            try:
                policy_meta["atr"] = abs(float(candidate.entry) - float(candidate.stop))
            except (TypeError, ValueError):
                pass

        intent = ExecIntent(
            symbol=symbol,
            side=candidate.side,
            qty=float(qty),
            limit_price=float(candidate.entry),
            bracket=candidate.kind == "equity" and candidate.stop is not None and candidate.target is not None,
            asset_class="option" if candidate.kind == "option" else "equity",
            meta=policy_meta,
        )

        result = await self._submit_with_retry(intent, dry_run=self._mock_routing)
        with self._metrics_lock:
            self._metrics["routed"] += 1
            if result.get("accepted") or result.get("dry_run"):
                self._metrics["accepted"] += 1

        status = "accepted" if result.get("accepted") else "simulated" if result.get("dry_run") else "rejected"
        record["status"] = status
        record["execution"] = {k: v for k, v in result.items() if k not in {"accepted"}}
        reason = result.get("reason")
        if reason:
            record.setdefault("filters", []).append(str(reason))
            if "alpaca_unauthorized" in str(reason):
                self._broker_disabled = True
                self._mock_routing = True
        self._record_decision(record)

    async def _submit_with_retry(
        self,
        intent: ExecIntent,
        dry_run: bool | None = None,
        *,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        dry_run_flag = self._mock_routing if dry_run is None else bool(dry_run)

        try:
            submission = self.router.submit(intent, dry_run=dry_run_flag)
            if inspect.isawaitable(submission):
                result = await submission  # type: ignore[assignment]
            else:
                result = submission
        except Exception as exc:  # noqa: BLE001
            log.exception("router submission error", extra={"symbol": intent.symbol, "error": str(exc)})
            self._last_error = str(exc)
            return {"accepted": False, "reason": f"router_error:{exc}"}

        if not isinstance(result, Mapping):
            try:
                result = dict(result)  # type: ignore[arg-type]
            except Exception:
                result = {
                    "accepted": bool(getattr(result, "accepted", False)),
                    "reason": getattr(result, "reason", None),
                    "dry_run": bool(getattr(result, "dry_run", dry_run_flag)),
                }

        if result.get("accepted") or result.get("dry_run") or dry_run_flag:
            return result

        reason = str(result.get("reason", "") or "")
        reason_lower = reason.lower()
        if any(marker in reason_lower for marker in DUP_KEYS) and max_retries > 0:
            await asyncio.sleep(0.01)
            retry_id_prefix = intent.client_order_id or "gt"
            retry_intent = replace(
                intent,
                client_order_id=f"{retry_id_prefix}-retry-{uuid.uuid4().hex[:6]}",
            )
            return await self._submit_with_retry(
                retry_intent,
                dry_run=dry_run_flag,
                max_retries=max_retries - 1,
            )

        if "alpaca_unauthorized" in reason_lower:
            self._broker_disabled = True
            self._mock_routing = True

        return result

    async def route_top_event(self, proposals: Sequence[Any]) -> Any:
        """
        Pick the highest-EV candidate; break ties *stably* (preserve input order).
        Return router result or None if blocked by policy flag.
        """
        if not proposals:
            log.info("route_top_event: no proposals")
            return None

        ranked = sorted(
            proposals,
            key=lambda cand: tuple([-x for x in _ev_and_secondary(cand)]),
        )
        top = ranked[0]
        identifier = getattr(top, "client_order_id", None) or _get_str(
            top, ("symbol", "underlying", "ticker", "meta.symbol"), ""
        )
        log.info("route_top_event: selected=%s", identifier)

        allow = True
        for name in ("should_trade", "allow", "approved", "ok"):
            v = _dig(top, name)
            if v is not None:
                allow = bool(v)
                break

        if not allow:
            log.info("route_top_event: blocked by policy gate")
            return None

        submit = getattr(self.router, "submit", None)
        if submit is None:
            log.error("route_top_event: router missing submit method")
            return None

        async def _invoke_submit() -> Any:
            if asyncio.iscoroutinefunction(submit):
                return await submit(top)  # type: ignore[arg-type]
            result_inner = submit(top)  # type: ignore[arg-type]
            if inspect.isawaitable(result_inner):
                result_inner = await result_inner
            return result_inner

        try:
            result = await _invoke_submit()
        except Exception as exc:  # noqa: BLE001
            log.exception("route_top_event: submit failed: %s", exc)
            raise

        accepted = getattr(result, "accepted", None)
        reason = getattr(result, "reason", None)
        if accepted is None and isinstance(result, dict):
            accepted = bool(result.get("accepted"))
            reason = result.get("reason")

        if not accepted and _is_duplicate_coid(reason):
            log.warning("Duplicate client_order_id detected; retrying submit once.")
            try:
                result = await _invoke_submit()
            except Exception as exc:  # noqa: BLE001
                log.exception("route_top_event: submit retry failed: %s", exc)
                raise

        return result

    def _probabilities(self, symbols: Sequence[str]) -> dict[str, float | None]:
        predictor = self.ml_predictor
        if predictor is None or not symbols:
            return {}

        try_methods: list[tuple[str, Any]] = []
        for name in ("predict_many", "predict", "predict_proba", "predict_symbols"):
            method = getattr(predictor, name, None)
            if callable(method):
                try_methods.append((name, method))
        if not try_methods:
            return {}

        symbols_upper = [_uppercase(s) for s in symbols]
        for name, method in try_methods:
            try:
                output = method(symbols_upper)
            except TypeError:
                continue
            except Exception as exc:  # noqa: BLE001
                log.debug("ml predictor %s failed: %s", name, exc)
                continue
            mapping: dict[str, float | None] = {}
            if isinstance(output, Mapping):
                for key, value in output.items():
                    if value is None:
                        continue
                    try:
                        mapping[_uppercase(str(key))] = float(value)
                    except (TypeError, ValueError):
                        continue
            elif isinstance(output, Iterable):
                values = list(output)
                if len(values) == len(symbols_upper):
                    for idx, raw in enumerate(values):
                        if raw is None:
                            continue
                        try:
                            mapping[symbols_upper[idx]] = float(raw)
                        except (TypeError, ValueError):
                            continue
            if mapping:
                return mapping

        result: dict[str, float | None] = {}
        for symbol in symbols_upper:
            for name, method in try_methods:
                try:
                    value = method(symbol)
                except TypeError:
                    continue
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(value, Mapping):
                    if symbol in value:
                        try:
                            result[symbol] = float(value[symbol])
                        except (TypeError, ValueError):
                            pass
                        break
                elif isinstance(value, Iterable):
                    seq = list(value)
                    if seq:
                        try:
                            result[symbol] = float(seq[-1])
                        except (TypeError, ValueError):
                            pass
                        break
                else:
                    try:
                        result[symbol] = float(value)
                    except (TypeError, ValueError):
                        pass
                    else:
                        break
        return result

    def _direction_probability(
        self, candidate: SignalCandidate, p_up: float | None
    ) -> float | None:
        if p_up is None:
            return None
        if candidate.side == "buy":
            return p_up
        return max(0.0, min(1.0, 1.0 - p_up))

    def _expected_value(
        self,
        candidate: SignalCandidate,
        direction_prob: float | None,
    ) -> float:
        if (
            direction_prob is not None
            and candidate.stop is not None
            and candidate.target is not None
        ):
            entry = float(candidate.entry)
            stop = float(candidate.stop)
            target = float(candidate.target)
            if candidate.side == "buy":
                gain = target - entry
                loss = entry - stop
            else:
                gain = entry - target
                loss = stop - entry
            gain = max(gain, 0.0)
            loss = max(loss, 0.0)
            downside_prob = max(0.0, min(1.0, 1.0 - direction_prob))
            return float(direction_prob * gain - downside_prob * loss)
        return float(candidate.confidence)

    def _size_candidate(self, candidate: SignalCandidate) -> int:
        budget = self._risk_budget()
        entry = max(float(candidate.entry), 1e-6)
        if candidate.stop is not None:
            risk_per_unit = abs(entry - float(candidate.stop))
            if risk_per_unit <= 1e-6:
                risk_per_unit = max(entry * 0.01, 0.5)
            raw_qty = budget / risk_per_unit if risk_per_unit > 0 else 0.0
        else:
            raw_qty = budget / entry
        confidence_scale = max(0.25, min(float(candidate.confidence), 2.0))
        qty = int(max(raw_qty * confidence_scale, 0.0))
        return max(qty, 0)

    def _account_equity_snapshot(self) -> float | None:
        state = getattr(self.risk_manager, "state", None)
        getter = getattr(state, "get_account_equity", None) if state is not None else None
        if not callable(getter):
            return None
        try:
            value = getter()
        except Exception:  # pragma: no cover - defensive
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _risk_budget(self) -> float:
        try:
            budget = getattr(self.risk_manager, "_risk_budget_dollars", None)
            if callable(budget):
                value = float(budget())
            else:
                value = 0.0
        except Exception:
            value = 0.0
        return max(value, 0.0)

    def _record_decision(self, record: dict[str, Any]) -> None:
        record.setdefault("timestamp", datetime.utcnow().isoformat())
        record.setdefault("filters", [])
        self._last_decisions.append(record)

    def _reset_metrics(self) -> None:
        with self._metrics_lock:
            for key in self._metrics:
                self._metrics[key] = 0

    def _infer_mock_mode(self) -> bool:
        broker = getattr(self.router, "broker", None)
        configured = True
        if broker is not None:
            try:
                configured = bool(broker.is_configured())
            except Exception:  # noqa: BLE001
                configured = False
        return bool(MOCK_MODE or not configured or self._broker_disabled)
