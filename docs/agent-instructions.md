# Agent Instructions

**Purpose:** Autonomously trade (paper by default) using market data + sentiment, under strict risk controls.

**Loop:** ingest → score → decide → risk → execute → log → learn.

## Inputs
- Market bars (1m or better), fundamentals (optional), sentiment (news-first; social only with bias filters).
- Live account equity (when available) for sizing; else MAX_NOTIONAL fallback.

## Hard risk gates (deny with reason)
- Kill switch; daily loss limit; per-trade risk % of equity; max positions; per-symbol notional cap; cooldowns.
- Options guardrails: min OI/volume, delta band, max price, DTE window.

## Strategy
- Equities: ORB + momentum with sentiment gating; disable in choppy regimes.
- Options: directional call/put via selector (target delta band, liquidity, DTE).
- Universe: base symbols + add top sentiment movers; cap watchlist.

## Execution
- Paper unless `TRADING_MODE=live` **and** `LIVE_CONFIRM=I_UNDERSTAND`.
- Idempotent submits, retries with backoff, brackets for equities.

## Observability & Safety
- JSON logs with trace_id; metrics counters; /healthz, /readyz (if SERVICE_PORT>0).
- No PII in logs; redact secrets; never store raw API keys.
