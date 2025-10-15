"""SQLite-backed order management store."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

__all__ = [
    "OmsStore",
    "ORDER_STATES",
    "TERMINAL_STATES",
    "OPEN_STATES",
]


ORDER_STATES = (
    "new",
    "submitting",
    "accepted",
    "partially_filled",
    "filled",
    "canceled",
    "rejected",
    "error",
)

OPEN_STATES = {"new", "submitting", "accepted", "partially_filled"}
TERMINAL_STATES = {"filled", "canceled", "rejected", "error"}


_CREATE_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id TEXT NOT NULL,
        broker_order_id TEXT,
        symbol TEXT,
        side TEXT,
        qty REAL,
        filled_qty REAL,
        limit_price REAL,
        stop_price REAL,
        take_profit REAL,
        tif TEXT,
        state TEXT NOT NULL,
        intent_hash TEXT,
        last_update_ts TEXT NOT NULL,
        raw_json TEXT
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_order_id);",
    "CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state);",
    """
    CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_order_id TEXT NOT NULL,
        event_type TEXT,
        fill_qty REAL,
        fill_price REAL,
        event_ts TEXT,
        raw_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_exec_coid ON executions(client_order_id);",
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        qty REAL,
        avg_price REAL,
        last_update_ts TEXT NOT NULL,
        raw_json TEXT
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);",
    """
    CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        category TEXT,
        message TEXT,
        details TEXT
    );
    """,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: Mapping[str, Any] | None) -> str | None:
    if not payload:
        return None
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        return json.dumps(dict(payload), default=str)


class OmsStore:
    """Thread-safe SQLite store for orders, executions and journal entries."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._conn:
            for ddl in _CREATE_TABLES:
                self._conn.execute(ddl)

    # ------------------------------------------------------------------
    def upsert_order(
        self,
        *,
        client_order_id: str,
        state: str,
        intent_hash: str | None = None,
        broker_order_id: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        qty: float | None = None,
        filled_qty: float | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        take_profit: float | None = None,
        tif: str | None = None,
        raw: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "client_order_id": client_order_id,
            "broker_order_id": broker_order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "filled_qty": filled_qty,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "take_profit": take_profit,
            "tif": tif,
            "state": state,
            "intent_hash": intent_hash,
            "last_update_ts": _utcnow(),
            "raw_json": _json_dumps(raw),
        }
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO orders (
                    client_order_id, broker_order_id, symbol, side, qty,
                    filled_qty, limit_price, stop_price, take_profit, tif,
                    state, intent_hash, last_update_ts, raw_json
                ) VALUES (
                    :client_order_id, :broker_order_id, :symbol, :side, :qty,
                    :filled_qty, :limit_price, :stop_price, :take_profit, :tif,
                    :state, :intent_hash, :last_update_ts, :raw_json
                )
                ON CONFLICT(client_order_id) DO UPDATE SET
                    broker_order_id=excluded.broker_order_id,
                    symbol=excluded.symbol,
                    side=excluded.side,
                    qty=excluded.qty,
                    filled_qty=excluded.filled_qty,
                    limit_price=excluded.limit_price,
                    stop_price=excluded.stop_price,
                    take_profit=excluded.take_profit,
                    tif=excluded.tif,
                    state=excluded.state,
                    intent_hash=excluded.intent_hash,
                    last_update_ts=excluded.last_update_ts,
                    raw_json=excluded.raw_json
                ;
                """,
                payload,
            )

    def update_order_state(
        self,
        client_order_id: str,
        *,
        state: str,
        broker_order_id: str | None = None,
        filled_qty: float | None = None,
        raw: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        fields: MutableMapping[str, Any] = {
            "state": state,
            "last_update_ts": _utcnow(),
        }
        if raw is not None:
            fields["raw_json"] = _json_dumps(raw)
        if broker_order_id is not None:
            fields["broker_order_id"] = broker_order_id
        if filled_qty is not None:
            fields["filled_qty"] = filled_qty
        if extra:
            for key, value in extra.items():
                if key in {"symbol", "side", "qty", "limit_price", "tif"}:
                    fields[key] = value
        assigns = ", ".join(f"{col} = :{col}" for col in fields)
        payload = dict(fields)
        payload["client_order_id"] = client_order_id
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE orders SET {assigns} WHERE client_order_id = :client_order_id",
                payload,
            )

    def append_execution(
        self,
        client_order_id: str,
        *,
        event_type: str,
        fill_qty: float | None,
        fill_price: float | None,
        event_ts: str | None,
        raw: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "client_order_id": client_order_id,
            "event_type": event_type,
            "fill_qty": fill_qty,
            "fill_price": fill_price,
            "event_ts": event_ts or _utcnow(),
            "raw_json": _json_dumps(raw),
        }
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO executions (
                    client_order_id, event_type, fill_qty, fill_price, event_ts, raw_json
                ) VALUES (
                    :client_order_id, :event_type, :fill_qty, :fill_price, :event_ts, :raw_json
                );
                """,
                payload,
            )

    def replace_positions(self, positions: Iterable[Mapping[str, Any]]) -> None:
        now = _utcnow()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM positions")
            for position in positions:
                payload = {
                    "symbol": position.get("symbol"),
                    "qty": position.get("qty"),
                    "avg_price": position.get("avg_entry_price") or position.get("avg_price"),
                    "last_update_ts": now,
                    "raw_json": _json_dumps(position),
                }
                self._conn.execute(
                    """
                    INSERT INTO positions (symbol, qty, avg_price, last_update_ts, raw_json)
                    VALUES (:symbol, :qty, :avg_price, :last_update_ts, :raw_json);
                    """,
                    payload,
                )

    def append_journal(
        self,
        *,
        category: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "ts": _utcnow(),
            "category": category,
            "message": message,
            "details": json.dumps(details, sort_keys=True, default=str) if details else None,
        }
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO journal (ts, category, message, details)
                VALUES (:ts, :category, :message, :details);
                """,
                payload,
            )

    def tail_journal(self, n: int = 20) -> List[Dict[str, Any]]:
        if n <= 0:
            return []
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "SELECT ts, category, message, details FROM journal ORDER BY id DESC LIMIT ?",
                (int(n),),
            )
            rows = cursor.fetchall()
        items: List[Dict[str, Any]] = []
        for row in reversed(rows):
            payload = {
                "ts": row["ts"],
                "category": row["category"],
                "message": row["message"],
            }
            details_raw = row["details"]
            if details_raw:
                try:
                    payload["details"] = json.loads(details_raw)
                except json.JSONDecodeError:
                    payload["details"] = details_raw
            items.append(payload)
        return items

    def get_open_orders(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "SELECT * FROM orders WHERE state IN ({}) ORDER BY last_update_ts DESC".format(
                    ",".join("?" for _ in OPEN_STATES)
                ),
                tuple(OPEN_STATES),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_order_by_coid(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "SELECT * FROM orders WHERE client_order_id = ?",
                (client_order_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def get_order_by_intent(self, intent_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "SELECT * FROM orders WHERE intent_hash = ? ORDER BY last_update_ts DESC LIMIT 1",
                (intent_hash,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def metrics_snapshot(self) -> Dict[str, Any]:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "SELECT state, COUNT(*) AS count FROM orders GROUP BY state"
            )
            state_rows = cursor.fetchall()
            exec_cursor = self._conn.execute(
                "SELECT COUNT(*) FROM executions WHERE event_type = 'fill'"
            )
            fills_total = exec_cursor.fetchone()[0]
        states: MutableMapping[str, int] = defaultdict(int)
        for row in state_rows:
            states[str(row["state"])] = int(row["count"])
        return {
            "orders_by_state": dict(states),
            "fills_total": int(fills_total),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

