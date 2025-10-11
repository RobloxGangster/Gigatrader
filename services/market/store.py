"""Persistence layer for TimescaleDB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import threading

import psycopg2
import psycopg2.pool
from psycopg2.extras import Json


@dataclass(slots=True)
class BarRow:
    """Structured representation of a bar row for persistence."""

    symbol: str
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    rsi: Optional[float]
    atr: Optional[float]
    zscore: Optional[float]
    orb_state: Dict[str, Any]
    orb_breakout: int


class TSStore:
    """Simple connection-pooled wrapper around TimescaleDB."""

    def __init__(self, url: str) -> None:
        if not url:
            raise RuntimeError("TIMESCALE_URL is required for Phase 1")
        self._url = url
        self._pool = psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=6, dsn=url)
        self._lock = threading.Lock()
        self._init_schema()

    def _exec(self, sql: str, args: Optional[Tuple[Any, ...]] = None) -> None:
        with self._lock:
            conn = self._pool.getconn()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, args or ())
            finally:
                self._pool.putconn(conn)

    def _init_schema(self) -> None:
        self._exec(
            """
            CREATE EXTENSION IF NOT EXISTS timescaledb;
            CREATE TABLE IF NOT EXISTS bars(
                symbol TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                rsi DOUBLE PRECISION,
                atr DOUBLE PRECISION,
                zscore DOUBLE PRECISION,
                orb_state JSONB,
                orb_breakout INTEGER,
                PRIMARY KEY(symbol, ts)
            );
            SELECT create_hypertable('bars', 'ts', if_not_exists => TRUE);
            CREATE INDEX IF NOT EXISTS bars_ts_idx ON bars(ts DESC);
            CREATE INDEX IF NOT EXISTS bars_sym_idx ON bars(symbol);
            """
        )

    def write(self, row: BarRow) -> None:
        self._exec(
            """
            INSERT INTO bars(
                symbol, ts, open, high, low, close, volume,
                rsi, atr, zscore, orb_state, orb_breakout
            ) VALUES (
                %(symbol)s, %(ts)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s,
                %(rsi)s, %(atr)s, %(zscore)s, %(orb_state)s, %(orb_breakout)s
            )
            ON CONFLICT (symbol, ts)
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                rsi = EXCLUDED.rsi,
                atr = EXCLUDED.atr,
                zscore = EXCLUDED.zscore,
                orb_state = EXCLUDED.orb_state,
                orb_breakout = EXCLUDED.orb_breakout;
            """,
            {
                "symbol": row.symbol,
                "ts": row.ts,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "rsi": row.rsi,
                "atr": row.atr,
                "zscore": row.zscore,
                "orb_state": Json(row.orb_state) if row.orb_state is not None else None,
                "orb_breakout": row.orb_breakout,
            },
        )
