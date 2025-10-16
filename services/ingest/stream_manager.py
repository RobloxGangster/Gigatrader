"""Stream ingestion manager with reconnects, persistence and status reporting."""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter


@dataclass
class StreamState:
    """Represents persisted stream progress."""

    last_seq: int = 0
    last_heartbeat: Optional[str] = None
    reconnect_count: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamState":
        return cls(
            last_seq=int(data.get("last_seq", 0) or 0),
            last_heartbeat=data.get("last_heartbeat"),
            reconnect_count=int(data.get("reconnect_count", 0) or 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_seq": self.last_seq,
            "last_heartbeat": self.last_heartbeat,
            "reconnect_count": self.reconnect_count,
        }


class StreamConnectionError(Exception):
    """Raised when the websocket connection is considered unhealthy."""


def _default_state_path() -> Path:
    return Path(__file__).resolve().parents[1] / "runtime" / "stream_state.json"


def _default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "runtime" / "stream_events.sqlite"


HandlerType = Callable[[Dict[str, Any], sqlite3.Connection], Awaitable[None] | None]


class StreamManager:
    """Manages websocket ingestion with persistence and health tracking."""

    def __init__(
        self,
        url: str,
        *,
        state_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
        handlers: Optional[Dict[str, HandlerType]] = None,
        websocket_factory: Optional[Callable[[str], Any]] = None,
        subscribe_builder: Optional[Callable[[int], Awaitable[Any] | Any]] = None,
        heartbeat_timeout: float = 30.0,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        self.url = url
        self.state_path = state_path or _default_state_path()
        self.db_path = db_path or _default_db_path()
        self.handlers = handlers or DEFAULT_HANDLERS
        self.websocket_factory = websocket_factory or self._default_websocket_factory
        self.subscribe_builder = subscribe_builder
        self.heartbeat_timeout = heartbeat_timeout
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay

        self._stop_event = asyncio.Event()
        self._state_lock = asyncio.Lock()
        self._db_lock = asyncio.Lock()
        self._state = self._load_state()
        self._connected = False
        self._active_ws: Any = None
        self._running = False

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    async def start(self) -> None:
        if self._running:
            raise RuntimeError("StreamManager already running")

        self._stop_event.clear()
        self._running = True
        backoff = self.reconnect_base_delay
        should_increment_reconnect = False

        try:
            while not self._stop_event.is_set():
                try:
                    async with self.websocket_factory(self.url) as ws:
                        self._active_ws = ws
                        if should_increment_reconnect:
                            async with self._state_lock:
                                self._state.reconnect_count += 1
                                await self._persist_state_locked()
                            should_increment_reconnect = False
                        await self._perform_subscribe(ws)
                        self._connected = True
                        backoff = self.reconnect_base_delay

                        while not self._stop_event.is_set():
                            try:
                                message = await asyncio.wait_for(
                                    ws.recv(), timeout=self.heartbeat_timeout
                                )
                            except asyncio.TimeoutError as exc:
                                raise StreamConnectionError("Heartbeat timeout") from exc

                            await self._process_message(message)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._connected = False
                    if self._active_ws is not None:
                        with contextlib.suppress(Exception):
                            await self._active_ws.close()
                        self._active_ws = None

                    if self._stop_event.is_set():
                        break

                    should_increment_reconnect = True

                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self.reconnect_max_delay)
                    continue
                finally:
                    self._connected = False
                    self._active_ws = None

                break
        finally:
            self._running = False

    async def stop(self) -> None:
        self._stop_event.set()
        if self._active_ws is not None:
            with contextlib.suppress(Exception):
                await self._active_ws.close()
        self._active_ws = None
        await self._persist_state()
        async with self._db_lock:
            self._conn.commit()
            self._conn.close()

    async def _perform_subscribe(self, ws: Any) -> None:
        if not self.subscribe_builder:
            return
        payload = self.subscribe_builder(self._state.last_seq)
        if inspect.isawaitable(payload):
            payload = await payload
        if payload is None:
            return
        message = payload
        if isinstance(payload, (dict, list)):
            message = json.dumps(payload)
        await ws.send(message)

    async def _process_message(self, message: Any) -> None:
        event = self._coerce_event(message)
        if event is None:
            return

        event_type = event.get("type")
        if event_type == "heartbeat":
            async with self._state_lock:
                self._state.last_heartbeat = datetime.utcnow().isoformat()
                await self._persist_state_locked()
            return

        seq = event.get("seq")
        async with self._state_lock:
            if seq is not None and seq <= self._state.last_seq:
                return
            if seq is not None:
                self._state.last_seq = int(seq)

        handler = self.handlers.get(event_type)
        if handler:
            async with self._db_lock:
                result = handler(event, self._conn)
                if inspect.isawaitable(result):
                    await result
                self._conn.commit()

        await self._persist_state()

    async def _persist_state(self) -> None:
        async with self._state_lock:
            await self._persist_state_locked()

    async def _persist_state_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._state.to_dict()
        self.state_path.write_text(json.dumps(data, indent=2))

    def _load_state(self) -> StreamState:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                return StreamState.from_dict(data)
            except Exception:
                pass
        return StreamState()

    def _ensure_tables(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                seq INTEGER,
                symbol TEXT,
                quantity REAL,
                price REAL,
                raw TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity REAL,
                mark REAL,
                bid REAL,
                ask REAL,
                seq INTEGER,
                raw TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reconcile_state (
                state_key TEXT PRIMARY KEY,
                seq INTEGER,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def _coerce_event(self, message: Any) -> Optional[Dict[str, Any]]:
        if message is None:
            return None
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8")
        if isinstance(message, str):
            try:
                return json.loads(message)
            except json.JSONDecodeError:
                return None
        if isinstance(message, dict):
            return message
        return None

    def _default_websocket_factory(self, url: str) -> Any:
        import websockets  # type: ignore

        return websockets.connect(url, ping_interval=None)

    def get_status(self) -> Dict[str, Any]:
        return {
            "last_seq": self._state.last_seq,
            "last_heartbeat": self._state.last_heartbeat,
            "reconnect_count": self._state.reconnect_count,
            "connected": self._connected,
        }


def create_status_router(manager: StreamManager) -> APIRouter:
    router = APIRouter()

    @router.get("/stream/status")
    def stream_status() -> Dict[str, Any]:
        return manager.get_status()

    return router


def quote_handler(event: Dict[str, Any], conn: sqlite3.Connection) -> None:
    data = event.get("data", {})
    symbol = data.get("symbol")
    if not symbol:
        return
    quantity = data.get("position_qty") or data.get("quantity") or data.get("qty")
    mark = data.get("mark") or data.get("price") or data.get("last")
    bid = data.get("bid")
    ask = data.get("ask")
    seq = event.get("seq")
    conn.execute(
        """
        INSERT INTO positions(symbol, quantity, mark, bid, ask, seq, raw)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            quantity=excluded.quantity,
            mark=excluded.mark,
            bid=excluded.bid,
            ask=excluded.ask,
            seq=excluded.seq,
            raw=excluded.raw
        """,
        (
            str(symbol),
            None if quantity is None else float(quantity),
            None if mark is None else float(mark),
            None if bid is None else float(bid),
            None if ask is None else float(ask),
            None if seq is None else int(seq),
            json.dumps(data, sort_keys=True),
        ),
    )


def trade_handler(event: Dict[str, Any], conn: sqlite3.Connection) -> None:
    data = event.get("data", {})
    fill_id = data.get("fill_id") or data.get("id") or event.get("seq")
    if fill_id is None:
        return
    symbol = data.get("symbol")
    quantity = data.get("quantity") or data.get("qty")
    price = data.get("price")
    seq = event.get("seq")
    conn.execute(
        """
        INSERT INTO fills(fill_id, seq, symbol, quantity, price, raw)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(fill_id) DO UPDATE SET
            seq=excluded.seq,
            symbol=excluded.symbol,
            quantity=excluded.quantity,
            price=excluded.price,
            raw=excluded.raw
        """,
        (
            str(fill_id),
            None if seq is None else int(seq),
            None if symbol is None else str(symbol),
            None if quantity is None else float(quantity),
            None if price is None else float(price),
            json.dumps(data, sort_keys=True),
        ),
    )


def order_update_handler(event: Dict[str, Any], conn: sqlite3.Connection) -> None:
    data = event.get("data", {})
    order_id = data.get("order_id") or data.get("id")
    if order_id is None:
        return
    seq = event.get("seq")
    conn.execute(
        """
        INSERT INTO reconcile_state(state_key, seq, payload, updated_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            seq=excluded.seq,
            payload=excluded.payload,
            updated_at=excluded.updated_at
        """,
        (
            str(order_id),
            None if seq is None else int(seq),
            json.dumps(data, sort_keys=True),
            datetime.utcnow().isoformat(),
        ),
    )


DEFAULT_HANDLERS: Dict[str, HandlerType] = {
    "quote": quote_handler,
    "trade": trade_handler,
    "order_update": order_update_handler,
}


__all__ = [
    "StreamManager",
    "create_status_router",
    "DEFAULT_HANDLERS",
    "quote_handler",
    "trade_handler",
    "order_update_handler",
]
