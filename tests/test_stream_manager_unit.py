import asyncio
import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.ingest.stream_manager import StreamManager, create_status_router


class FakeConnectionClosed(Exception):
    pass


class FakeWebSocket:
    def __init__(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        on_send: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self._messages: Deque[Dict[str, Any]] = deque(messages)
        self._on_send = on_send
        self._closed = False
        self.sent: List[Any] = []

    async def __aenter__(self) -> "FakeWebSocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._closed = True

    async def send(self, message: Any) -> None:
        if self._on_send:
            self._on_send(message)
        self.sent.append(message)

    async def recv(self) -> str:
        await asyncio.sleep(0)
        if self._closed:
            raise FakeConnectionClosed()
        if not self._messages:
            raise FakeConnectionClosed()
        payload = self._messages.popleft()
        return json.dumps(payload)

    async def close(self) -> None:
        self._closed = True


class FakeWebSocketFactory:
    def __init__(self, connections: Iterable[Iterable[Dict[str, Any]]]) -> None:
        self._connections = deque(connections)
        self.created: List[FakeWebSocket] = []

    def __call__(self, url: str) -> FakeWebSocket:
        try:
            messages = self._connections.popleft()
        except IndexError as exc:
            raise AssertionError("No more fake websocket connections available") from exc
        ws = FakeWebSocket(messages)
        self.created.append(ws)
        return ws


async def wait_for_condition(condition: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not condition():
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_stream_manager_ingests_and_recovers(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite"
    state_path = tmp_path / "stream_state.json"

    first_connection = [
        {"type": "trade", "seq": 1, "data": {"fill_id": "f1", "symbol": "AAPL", "qty": 5, "price": 195.0}},
        {"type": "heartbeat"},
    ]
    second_connection = [
        {"type": "quote", "seq": 2, "data": {"symbol": "AAPL", "bid": 194.5, "ask": 195.5, "position_qty": 5}},
        {"type": "order_update", "seq": 3, "data": {"order_id": "o1", "status": "filled", "filled_qty": 5}},
    ]
    factory = FakeWebSocketFactory([first_connection, second_connection])

    subscribe_calls: List[int] = []

    def subscribe_builder(seq: int) -> Dict[str, Any]:
        subscribe_calls.append(seq)
        return {"resume_from": seq}

    manager = StreamManager(
        "wss://example",
        db_path=db_path,
        state_path=state_path,
        websocket_factory=factory,
        subscribe_builder=subscribe_builder,
        heartbeat_timeout=0.2,
        reconnect_base_delay=0.01,
        reconnect_max_delay=0.05,
    )

    task = asyncio.create_task(manager.start())

    await wait_for_condition(lambda: manager.get_status()["last_seq"] >= 3, timeout=2.0)

    await manager.stop()
    await task

    assert subscribe_calls[0] == 0

    with sqlite3.connect(db_path) as conn:
        fills = conn.execute("SELECT fill_id, symbol, quantity, price FROM fills").fetchall()
        positions = conn.execute("SELECT symbol, bid, ask, quantity FROM positions").fetchall()
        reconcile = conn.execute("SELECT state_key, payload FROM reconcile_state").fetchall()

    assert len(fills) == 1
    assert fills[0][0] == "f1"
    assert pytest.approx(fills[0][2]) == 5
    assert pytest.approx(fills[0][3]) == 195.0

    assert len(positions) == 1
    assert positions[0][0] == "AAPL"
    assert pytest.approx(positions[0][1]) == 194.5
    assert pytest.approx(positions[0][2]) == 195.5

    assert len(reconcile) == 1
    payload = json.loads(reconcile[0][1])
    assert payload["order_id"] == "o1"
    assert payload["status"] == "filled"

    persisted = json.loads(state_path.read_text())
    assert persisted["last_seq"] == 3
    assert persisted["reconnect_count"] == 1
    assert persisted["last_heartbeat"] is not None

    third_connection = [
        {"type": "trade", "seq": 4, "data": {"fill_id": "f2", "symbol": "MSFT", "qty": 1, "price": 300.0}},
    ]
    factory2 = FakeWebSocketFactory([third_connection])

    subscribe_calls_second: List[int] = []

    def subscribe_builder_second(seq: int) -> Dict[str, Any]:
        subscribe_calls_second.append(seq)
        return {"resume_from": seq}

    manager2 = StreamManager(
        "wss://example",
        db_path=db_path,
        state_path=state_path,
        websocket_factory=factory2,
        subscribe_builder=subscribe_builder_second,
        heartbeat_timeout=0.2,
        reconnect_base_delay=0.01,
        reconnect_max_delay=0.05,
    )

    task2 = asyncio.create_task(manager2.start())

    await wait_for_condition(lambda: manager2.get_status()["last_seq"] >= 4, timeout=2.0)

    await manager2.stop()
    await task2

    assert subscribe_calls_second[0] == 3

    with sqlite3.connect(db_path) as conn:
        fills = conn.execute("SELECT fill_id FROM fills ORDER BY seq").fetchall()
    assert [row[0] for row in fills] == ["f1", "f2"]


@pytest.mark.asyncio
async def test_status_route_reports_stream_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite"
    state_path = tmp_path / "stream_state.json"

    manager = StreamManager(
        "wss://example",
        db_path=db_path,
        state_path=state_path,
        websocket_factory=FakeWebSocketFactory([[{"type": "heartbeat"}]]),
        heartbeat_timeout=0.2,
        reconnect_base_delay=0.01,
        reconnect_max_delay=0.05,
    )

    manager._state.last_seq = 42
    manager._state.last_heartbeat = "2024-01-01T00:00:00"
    manager._state.reconnect_count = 7

    app = FastAPI()
    app.include_router(create_status_router(manager))
    client = TestClient(app)

    response = client.get("/stream/status")
    assert response.status_code == 200
    body = response.json()
    assert body["last_seq"] == 42
    assert body["last_heartbeat"] == "2024-01-01T00:00:00"
    assert body["reconnect_count"] == 7
    assert body["connected"] is False

    await manager.stop()
