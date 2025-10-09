# Alpaca Integration Notes

- Use `alpaca-py` unified clients for trading and market data.
- Paper trading endpoints are used by default; `LIVE_TRADING=true` must be set explicitly before enabling live endpoints.
- Read rate limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`) from every response and feed into `RateLimitedQueue`.
- Websocket streams should be initialised via `AlpacaDataProvider.ensure_streams`. Reconnect on disconnects and log reasons.
- For options orders, ensure contract specifications include multiplier, greeks, and liquidity metrics. Fail closed when data stale.
- All secrets must be stored in `.env` and loaded through `AlpacaSettings` from `core.config`.
