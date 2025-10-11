#!/usr/bin/env python3
"""Phase 1 verification script.

This script checks that the required Phase 1 files, dependencies, Make targets,
and tests are present. If a ``TIMESCALE_URL`` environment variable is provided,
it also verifies the TimescaleDB schema and performs a small write/read test via
``TSStore``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
FAIL = 0

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ok(message: str) -> None:
    print(f"OK {message}")


def warn(message: str) -> None:
    print(f"WARN {message}")


def fail(message: str) -> None:
    global FAIL
    FAIL = 1
    print(f"FAIL {message}")


def must_exist(paths: Iterable[str]) -> None:
    missing = [path for path in paths if not (ROOT / path).exists()]
    if missing:
        fail("missing: " + ", ".join(missing))
    else:
        ok("all required files present")


def check_requirements() -> None:
    core_path = ROOT / "requirements-core.in"
    core_text = core_path.read_text()
    needed = ["psycopg2-binary", "pandas", "pyarrow"]
    missing = [pkg for pkg in needed if pkg not in core_text]
    if missing:
        fail("requirements-core.in missing: " + ", ".join(missing))
    else:
        ok("requirements-core.in contains psycopg2-binary, pandas, pyarrow")


def check_make_targets() -> None:
    mk_text = (ROOT / "Makefile").read_text()
    for target in ("db-init", "run-market"):
        phony_pattern = re.compile(rf"^\.PHONY:\s.*\b{re.escape(target)}\b", re.MULTILINE)
        target_pattern = re.compile(rf"^{re.escape(target)}:\s", re.MULTILINE)
        if not (phony_pattern.search(mk_text) or target_pattern.search(mk_text)):
            fail(f"Makefile missing target: {target}")
            return
    ok("Makefile targets present (db-init, run-market)")


def grep_token(file_rel: str, tokens: Iterable[str]) -> None:
    text = (ROOT / file_rel).read_text().lower()
    for token in tokens:
        if token.lower() not in text:
            fail(f"{file_rel} missing token: {token}")
            return
    ok(f"{file_rel} contains required tokens: {', '.join(tokens)}")


def verify_timescale() -> None:
    url = os.getenv("TIMESCALE_URL")
    if not url:
        warn("TIMESCALE_URL not set; skipping DB checks")
        return

    try:
        import psycopg2
        import psycopg2.extras
    except Exception as exc:  # pragma: no cover - import guard
        fail(f"psycopg2 not importable: {exc}")
        return

    from services.market.store import BarRow, TSStore

    # Verify hypertable, primary key, and indexes.
    with psycopg2.connect(url) as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            """
            SELECT hypertable_name
            FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'bars';
            """
        )
        if not cur.fetchone():
            fail("bars hypertable not found (run `make db-init`)")
        else:
            ok("bars hypertable present")

        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'bars' AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position;
            """
        )
        primary_key = [row[0] for row in cur.fetchall()]
        if primary_key != ["symbol", "ts"]:
            fail(f"primary key expected (symbol, ts), got {primary_key}")
        else:
            ok("primary key (symbol, ts) present")

        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'bars';")
        indexes = {row[0] for row in cur.fetchall()}
        missing_indexes = {"bars_ts_idx", "bars_sym_idx"} - indexes
        for index in missing_indexes:
            fail(f"missing index: {index}")
        if not missing_indexes:
            ok("required indexes present")

    # Perform a tiny write/read via TSStore.
    store = TSStore(url)

    import datetime as _dt

    ts = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc).isoformat()
    row = BarRow(
        symbol="TEST",
        ts=ts,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100.0,
        rsi=50.0,
        atr=0.2,
        zscore=0.1,
        orb_state={"high": 2.0, "low": 0.5, "active": False},
        orb_breakout=1,
    )
    store.write(row)

    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bars WHERE symbol = 'TEST' AND ts = %s;", (ts,))
        count = cur.fetchone()[0]
        if count != 1:
            fail("write/read check failed for symbol=TEST")
        else:
            ok("write/read check passed for symbol=TEST")


def run_pytests() -> None:
    tests = ["tests/test_indicators.py"]
    if os.getenv("TIMESCALE_URL"):
        tests.append("tests/test_timescale_schema.py")

    try:
        import pytest  # type: ignore
    except ModuleNotFoundError:
        warn("pytest not installed; running fallback test execution")
        try:
            from tests.test_indicators import (  # type: ignore
                test_atr_positive,
                test_orb_breakout,
                test_rsi_bounds,
                test_zscore_ready,
            )

            test_rsi_bounds()
            test_atr_positive()
            test_zscore_ready()
            test_orb_breakout()

            if os.getenv("TIMESCALE_URL"):
                from services.market.store import TSStore

                TSStore(os.getenv("TIMESCALE_URL", ""))
        except Exception as exc:  # pragma: no cover - fallback error path
            fail(f"fallback tests failed: {exc}")
        else:
            ok("fallback tests passed")
        return

    cmd = [sys.executable, "-m", "pytest", "-q", *tests]
    print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        fail("pytest failed")
    else:
        ok("pytest passed")


def main() -> None:
    must_exist(
        [
            "configs/market.yaml",
            "services/market/init.py",
            "services/market/indicators.py",
            "services/market/store.py",
            "services/market/loop.py",
            "tools/db_init.py",
            "tests/test_indicators.py",
            "Makefile",
            "requirements-core.in",
        ]
    )
    check_requirements()
    check_make_targets()
    grep_token(
        "services/market/loop.py",
        ["StockDataStream", "subscribe_bars", "TSStore", "BarRow"],
    )
    grep_token(
        "services/market/store.py",
        ["create_hypertable", "on conflict (symbol, ts)"],
    )
    run_pytests()
    verify_timescale()
    print("\nSUMMARY: " + ("PASS ✅" if FAIL == 0 else "FAIL ❌"))
    sys.exit(FAIL)


if __name__ == "__main__":
    main()

