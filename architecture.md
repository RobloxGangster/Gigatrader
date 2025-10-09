# Architecture Overview

Gigatrader follows a modular, event-driven architecture to separate concerns between data ingestion, strategy logic, risk controls, and execution.

## Core
- **Interfaces** define contracts for data providers, brokers, strategies, risk managers, and cost models.
- **Event Bus** enables loose coupling between components (e.g., market data stream feeding multiple strategies).
- **Rate Limiter** enforces broker API usage policies.
- **Kill Switch** provides instant halt via CLI and environment variables, failing closed by default.

## Data Layer
- Alpaca data provider wraps historical and streaming clients for equities and options.
- Symbol cache and batching (TODO) reduce redundant requests and respect rate limits.

## Execution Layer
- Alpaca broker adapter unifies order submission for equities and options, utilising idempotency keys and rate-limited queue.
- Risk checks occur before queue submission to avoid rejected orders.

## Strategies
- Equities Momentum + ORB: combines ATR, RSI, z-score, and opening range breakout logic (to be implemented) to produce bracket orders.
- Options Directional & Debit Spreads: uses underlying trend signals and greeks-based filters to construct trades.
- Regime module (TODO) evaluates volatility regimes to adjust strategy activation and sizing.

## Risk Management
- Configurable presets stored in YAML and documented separately.
- Global exposure, per-trade, and options-specific greeks/liquidity constraints enforced pre-trade.
- Portfolio state tracking (TODO) integrates with broker positions and backtest engine.

## Backtesting
- Event-driven engine simulates fills with latency, slippage, and partial fills.
- Metrics module computes risk-adjusted performance and supports Monte Carlo resampling (TODO).
- Walk-forward evaluation and hyperparameter sweeps (TODO) orchestrated via CLI.

## UI
- Streamlit dashboard provides layman-friendly visibility into performance, positions, and trade rationales.
- Risk preset toggles map to YAML-defined thresholds.

## Deployment Considerations
- Paper mode default, live mode guarded by environment flag and configuration validation.
- Secrets stored in `.env` and loaded with pydantic settings; never hard-coded.
- CI pipeline runs linting, type-checking, tests, and coverage.
