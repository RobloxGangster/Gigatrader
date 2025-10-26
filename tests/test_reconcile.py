import importlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.execution.audit import AuditLog
from app.execution.reconcile import Reconciler


class StubBroker:
    def __init__(self) -> None:
        submitted = datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc).isoformat()
        filled = datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc).isoformat()
        self._orders = [
            {
                "id": "stub-open",
                "client_order_id": "STUB-OPEN",
                "symbol": "AAPL",
                "side": "buy",
                "qty": 10,
                "filled_qty": 0,
                "status": "accepted",
                "type": "limit",
                "limit_price": 150.0,
                "stop_price": None,
                "submitted_at": submitted,
                "updated_at": submitted,
            },
            {
                "id": "stub-closed",
                "client_order_id": "STUB-CLOSED",
                "symbol": "MSFT",
                "side": "sell",
                "qty": 5,
                "filled_qty": 5,
                "status": "filled",
                "type": "limit",
                "limit_price": 320.0,
                "stop_price": None,
                "submitted_at": submitted,
                "updated_at": filled,
            },
        ]
        self._positions = [
            {
                "symbol": "AAPL",
                "qty": 10,
                "avg_entry": 145.0,
                "market_price": 150.0,
                "unrealized_pl": 50.0,
                "last_updated": None,
            }
        ]

    def list_orders(self, status: str = "all"):
        open_statuses = {"new", "accepted", "partially_filled"}
        closed_statuses = {"filled", "canceled", "rejected", "expired", "replaced"}
        if status == "open":
            return [o.copy() for o in self._orders if o["status"] in open_statuses]
        if status == "closed":
            return [o.copy() for o in self._orders if o["status"] in closed_statuses]
        return [o.copy() for o in self._orders]

    def list_positions(self):
        return [p.copy() for p in self._positions]

    def cancel_all(self):
        open_statuses = {"new", "accepted", "partially_filled"}
        now = datetime.now(timezone.utc).isoformat()
        canceled = 0
        for order in self._orders:
            if order["status"] in open_statuses:
                order["status"] = "canceled"
                order["updated_at"] = now
                canceled += 1
        return {"canceled": canceled, "failed": 0}


@pytest.fixture
def reconcile_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    os.environ["MOCK_MODE"] = "true"
    import backend.server as server_module

    server = importlib.reload(server_module)

    audit_log = AuditLog(tmp_path / "audit.ndjson")
    stub = StubBroker()
    reconciler = Reconciler(stub, audit_log, tmp_path / "state.json", mock_mode=True)

    monkeypatch.setattr(server, "_audit_log", audit_log, raising=False)
    monkeypatch.setattr(server, "_reconciler", reconciler, raising=False)
    monkeypatch.setattr(server, "_reconcile_broker", stub, raising=False)

    server.app.state.audit_log = audit_log
    server.app.state.reconciler = reconciler
    server.app.state.reconcile_broker = stub

    client = TestClient(server.app)
    try:
        yield client
    finally:
        client.close()


def test_sync_idempotent(tmp_path: Path):
    audit = AuditLog(tmp_path / "audit.ndjson")
    stub = StubBroker()
    reconciler = Reconciler(stub, audit, tmp_path / "state.json", mock_mode=True)

    first = reconciler.sync_once()
    assert first == {"seen": 2, "new": 2, "changed": 0, "unchanged": 0}

    second = reconciler.sync_once()
    assert second["new"] == 0
    assert second["unchanged"] >= 2

    events = audit.tail(10)
    order_new_events = [evt for evt in events if evt.get("event") == "order_new"]
    assert len(order_new_events) == 2
    summary_events = [evt for evt in events if evt.get("event") == "sync_summary"]
    assert len(summary_events) == 2
    assert summary_events[-1]["stats"]["unchanged"] >= 2


def test_audit_tail_endpoint(reconcile_client: TestClient):
    resp = reconcile_client.post("/orders/sync")
    assert resp.status_code == 200

    resp = reconcile_client.get("/trade/debug/audit_tail", params={"n": 5})
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    assert all("event" in item for item in payload)


def test_cancel_all_endpoint_exists(reconcile_client: TestClient):
    resp = reconcile_client.post("/orders/cancel_all")
    assert resp.status_code == 200
    payload = resp.json()
    assert "canceled" in payload
    assert isinstance(payload["canceled"], int)


def test_orders_list_normalized(reconcile_client: TestClient):
    reconcile_client.post("/orders/sync")
    resp = reconcile_client.get("/orders", params={"status": "all"})
    assert resp.status_code == 200
    orders = resp.json()
    assert isinstance(orders, list)
    assert orders
    required_keys = {
        "id",
        "client_order_id",
        "symbol",
        "side",
        "qty",
        "filled_qty",
        "status",
        "type",
        "limit_price",
        "stop_price",
        "submitted_at",
        "updated_at",
    }
    for order in orders:
        assert required_keys.issubset(order.keys())
