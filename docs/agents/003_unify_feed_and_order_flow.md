# Task 003 — SIP-first data, health checks, and order submission fix

**Goal:** Use SIP when available (fallback IEX), add staleness/latency checks, and fix order submission/validation.

### Deliverables
1) `src/app/data/entitlement.py`
   - Implement `sip_entitled(symbol="SPY")->bool` using `StockHistoricalDataClient` + `StockLatestTradeRequest(feed=SIP)`. Return True on success; False on exceptions.

2) `src/app/streaming.py` (replace file)
   - Decide feed once at startup via probe:
     - If `STRICT_SIP=true` and SIP not entitled ⇒ raise RuntimeError.
     - Else: SIP if entitled, otherwise IEX.
   - `stream_bars(symbols, minutes=None, on_health=None)` using `StockDataStream`.
   - Track staleness per symbol (`DATA_STALENESS_SEC`, default 5).
   - Compute latency per event; print in logs; call `on_health` on state changes.
   - Periodic watchdog marks symbols `STALE` if gap > threshold.

3) `src/app/execution/alpaca_orders.py` (replace file)
   - Provide:
     - `submit_order_sync(client, order_req)` → thin wrapper over `client.submit_order(order_data=order_req)`
     - `submit_order_async(client, order_req)` → `run_in_executor` wrapper
     - Builders with **strict validation**:
       - `build_market_order(symbol, qty, side, tif="DAY", client_order_id=None)`
       - `build_limit_order(symbol, qty, side, limit_price, tif="DAY", client_order_id=None)` → **raise ValueError if limit_price is None**
       - `build_bracket_market_order(symbol, qty, side, take_profit_limit, stop_loss, tif="GTC", client_order_id=None)`
       - `build_bracket_limit_order(symbol, qty, side, limit_price, take_profit_limit, stop_loss, tif="GTC", client_order_id=None)` → **limit_price required**
   - Ensure `OrderSide`, `TimeInForce`, `OrderClass`, `TakeProfitRequest`, `StopLossRequest` are correctly used.

4) Replace **all** usages of `TradingClient.submit_order_async` or `await client.submit_order(...)` with the new wrapper & builders. If the call site is synchronous, use `submit_order_sync`.

5) CLI (`src/app/cli.py`)
   - Add:
     - `verify-feed` → prints selected feed; non-zero exit if STRICT_SIP and SIP not available.
     - `feed-latency --symbols AAPL,MSFT --seconds 30` → stream briefly, print p50/p95 latency; non-zero if any symbol goes stale.
     - `place-test-order --type market|limit --symbol AAPL --qty 1 [--limit-price 123.45]`  
       PAPER only; refuse if `LIVE_TRADING=="true"`. For `type=limit`, **require** `--limit-price` else show a helpful error and exit 2. Submit and attempt cancel.

6) Tests
   - `tests/test_no_forbidden_calls.py` → assert no `TradingClient.submit_order_async` in code.
   - `tests/test_feed_selection.py` → probe fallback vs STRICT_SIP behavior (mock `sip_entitled`).
   - `tests/test_order_builders.py` → limit builders raise `ValueError` when `limit_price` missing; market builders don’t.
   - `tests/test_submit_wrappers.py` → wrapper routes to `submit_order` (use dummy client).

### Acceptance
- PAPER run no longer logs AttributeError and does not send invalid limit orders.
- SIP used when entitled; otherwise IEX with a visible warning. STRICT_SIP enforces fail-fast.
- `trade verify-feed`, `trade feed-latency`, and `trade place-test-order` behave as specified.

---
