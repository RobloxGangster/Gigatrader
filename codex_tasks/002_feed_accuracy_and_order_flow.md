# Task 002 — Data Accuracy & Order Flow Hardening

**Goal:** Implement data accuracy guards (staleness, cross-checks, latency) and expose them via CLI so developers can diagnose “live data isn’t accurate” fast. Keep order flow rules intact.

## Deliverables
1) **New module** `src/app/data/quality.py`:
   - `class FeedHealth`: tracks per-symbol last update, latency stats, flags (`OK|STALE|DEGRADED`).
   - `def note_event(symbol: str, event_ts: datetime, ingest_ts: datetime) -> None`
   - `def is_stale(symbol: str, now: datetime, staleness_sec: int) -> bool`
   - `def crosscheck_snapshot(symbols: list[str]) -> list[dict]`
     - Fetch current snapshots (use alpaca-py data client) and compare vs last stream values; return list of mismatches with deltas.
   - `def check_bar_continuity(symbols: list[str], start, end) -> list[dict]`
     - Load 1-minute bars and report gaps during regular session.

2) **Wire into streaming** `src/app/streaming.py`:
   - Accept callbacks or import `FeedHealth`.
   - On every bar, call `FeedHealth.note_event(...)`.
   - Add optional `on_health_change` callback to emit state transitions (e.g., to logs/UI).

3) **CLI commands** in `src/app/cli.py`:
   - `verify-data --symbols AAPL,MSFT --minutes 5`
     - Start the stream, run for N minutes, print staleness/latency summary.
   - `feed-latency --symbols AAPL,MSFT --seconds 30`
     - Stream for N seconds and report p50/p95 latency.
   - Both commands must **exit non-zero** if feed becomes STALE for any symbol.

4) **Env & config**
   - Read `ALPACA_DATA_FEED` (IEX default) and `DATA_STALENESS_SEC` (default 5).
   - Respect market hours (use broker clock) to avoid false positives in closed markets.

5) **Tests**
   - `tests/test_feed_selection.py` — setting `ALPACA_DATA_FEED=SIP` selects SIP; anything else selects IEX.
   - `tests/test_no_forbidden_calls.py` — forbid `TradingClient.submit_order_async` in codebase.
   - `tests/test_feed_health.py` — staleness turns true when gap > threshold; latency stats compute p50/p95.

## Hints (use these libraries)
- Streaming: `alpaca.data.live.StockDataStream`
- Snapshots/historical: `alpaca.data.StockHistoricalDataClient` + `StockSnapshotRequest`/`StockBarsRequest`
- Time: keep everything in UTC; use broker clock to gate market-hours checks.

## Acceptance criteria
- Streaming logs show latency per symbol and **flag STALED** if no updates within threshold.
- CLI `verify-data` returns exit code 0 when healthy; non-zero when stale.
- Snapshot cross-check emits structured log records on mismatches.
