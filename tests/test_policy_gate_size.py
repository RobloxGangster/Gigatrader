import types
from pathlib import Path

import pytest

from app.execution.audit import AuditLog
from app.execution.router import ExecIntent, OrderRouter
from services.policy.gates import should_trade
from services.policy.sizing import size_position


class StubRisk:
    def pre_trade_check(self, proposal):
        return types.SimpleNamespace(allow=True, reason="ok")


class StubState:
    def __init__(self):
        self._map: dict[str, str] = {}

    def seen(self, key: str) -> bool:
        return key in self._map

    def client_id_for(self, key: str) -> str | None:
        return self._map.get(key)

    def remember(self, key: str, cid: str, **_: object) -> None:
        self._map[key] = cid

    def forget(self, key: str) -> None:
        self._map.pop(key, None)

    def map_provider_id(self, cid: str, provider_id: str | None) -> None:  # pragma: no cover - noop
        self._map[cid] = provider_id or ""


class StubStore:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.intent_map: dict[str, dict] = {}
        self.journal: list[dict] = []

    def get_order_by_intent(self, key: str) -> dict | None:
        return self.intent_map.get(key)

    def get_order_by_coid(self, cid: str) -> dict | None:
        return self.orders.get(cid)

    def upsert_order(self, *, client_order_id: str, intent_hash: str | None = None, raw=None, **kwargs) -> None:
        record = {"client_order_id": client_order_id, **kwargs, "raw": raw}
        self.orders[client_order_id] = record
        if intent_hash:
            self.intent_map[intent_hash] = record

    def update_order_state(self, client_order_id: str, **kwargs) -> None:
        self.orders.setdefault(client_order_id, {}).update(kwargs)

    def append_journal(self, **kwargs) -> None:
        self.journal.append(kwargs)

    def append_execution(self, *args, **kwargs) -> None:  # pragma: no cover - noop
        return None


class StubBroker:
    def __init__(self):
        self.calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def place_limit_bracket(self, **order):
        self.calls.append(order)
        return {
            "id": "broker-1",
            "client_order_id": order.get("client_order_id"),
            "status": "accepted",
            "filled_qty": "0",
            "qty": str(order.get("qty", 0)),
            "limit_price": str(order.get("limit_price", 0.0)),
        }

    def map_order_state(self, status):
        return status or "accepted"


@pytest.fixture
def router(tmp_path: Path) -> OrderRouter:
    audit = AuditLog(tmp_path / "audit.jsonl")
    router = OrderRouter(
        risk=StubRisk(),
        state=StubState(),
        store=StubStore(),
        audit=audit,
        metrics=None,
    )
    router.broker = StubBroker()  # type: ignore[assignment]
    return router


def test_should_trade_passes_with_positive_alpha():
    ctx = {
        "momo_score": 0.3,
        "mr_score": 0.2,
        "brk_score": 0.25,
        "swing_score": 0.2,
        "proba_up": 0.65,
    }
    allow, info = should_trade(ctx)
    assert allow is True
    assert info["alpha"] >= info["alpha_min"]
    assert "ok" in info["reason_codes"]


def test_should_trade_blocks_on_low_metrics():
    allow, info = should_trade({"alpha": 0.05, "proba_up": 0.4})
    assert allow is False
    assert "alpha_below_min" in info["reason_codes"]
    assert "proba_below_min" in info["reason_codes"]


def test_size_position_caps_daily_loss(monkeypatch):
    monkeypatch.setenv("DAILY_LOSS_CAP_BPS", "100")
    details = size_position(
        {
            "alpha": 0.6,
            "proba_up": 0.7,
            "atr": 2.0,
            "price": 100.0,
            "qty": 500,
            "account_equity": 200_000,
        }
    )
    assert details["risk_bps"] <= 100
    assert details["qty"] <= 500
    assert details["reason"] in {"ok", "capped_by_request", "daily_loss_cap"}


def test_size_position_returns_zero_when_no_edge():
    details = size_position({"alpha": -0.1, "qty": 100, "price": 50.0, "atr": 1.0, "account_equity": 100_000})
    assert details["qty"] == 0
    assert details["reason"] == "kelly_zero"


def test_order_router_policy_blocks_and_audits(router: OrderRouter, tmp_path: Path):
    intent = ExecIntent(
        symbol="AAPL",
        side="buy",
        qty=10,
        limit_price=150.0,
        meta={"alpha": 0.05, "proba_up": 0.4},
    )
    result = router.submit(intent)
    assert result["accepted"] is False
    assert result["reason"] == "policy_gate_blocked"
    assert result.get("status_code") == 202
    events = router.audit.tail()
    assert any(evt.get("event") == "policy_blocked" for evt in events)


def test_order_router_policy_allows_and_sizes(router: OrderRouter):
    intent = ExecIntent(
        symbol="MSFT",
        side="buy",
        qty=100,
        limit_price=50.0,
        meta={
            "alpha": 0.5,
            "proba_up": 0.7,
            "atr": 1.5,
            "account_equity": 150_000,
        },
    )
    result = router.submit(intent)
    assert result["accepted"] is True
    policy = result.get("policy") or {}
    sizing = policy.get("sizing") or {}
    assert sizing.get("qty") <= 100
    events = router.audit.tail()
    assert any(evt.get("event") == "policy_allow" for evt in events)
