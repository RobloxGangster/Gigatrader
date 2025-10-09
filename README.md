# Gigatrader

Gigatrader is a production-grade scaffold for an automated US equities and equity options trading platform built on **Python 3.11** and **alpaca-py**. The project emphasises guardrails-first design, paper trading by default, and transparent risk management for short-term trading strategies.

## Features
- Paper trading as default mode with environment flag required for live execution.
- Centralised async rate-limited execution queue with backoff and idempotent orders.
- Strategy scaffolds for equities momentum/ORB and options directional & debit spread trading.
- Configurable risk presets with pre-trade checks for equities and options.
- Event-driven backtester with placeholders for realistic execution modelling.
- Streamlit dashboard tailored for non-technical operators.
- CLI for orchestrating backtests, paper runs, live runs (guarded), reporting, and kill switch activation.

## Getting Started
1. Copy `.env.example` (if provided) and populate Alpaca credentials.
2. Install dependencies using `poetry install`.
3. Adjust `config.example.yaml` or create your own configuration.
4. Use `make setup` to bootstrap formatting hooks and virtual environment.
5. Run `make run-paper` to start a paper session once orchestration is implemented.

## Directory Layout
```
core/         # Interfaces, config, rate limiting, kill switch, utilities
data/         # Data provider adapters (Alpaca)
execution/    # Broker adapters and order routing
strategies/   # Strategy implementations and shared signal utilities
risk/         # Risk manager and presets
backtest/     # Backtesting engine, metrics, reports
ui/           # Streamlit application
scripts/      # CLI entrypoints and helper scripts
notebooks/    # Research and exploratory analysis
tests/        # Unit, property, and integration tests
```

## Guardrails
- Live trading requires `LIVE_TRADING=true` environment variable; otherwise the system fails closed.
- `trade halt` CLI command and `.kill_switch` file provide global kill-switch.
- Risk manager enforces global exposure, per-trade, and options-specific limits before every order.
- Rate limiter respects Alpaca rate limit headers and uses jittered exponential backoff.

## Streamlit UI
Launch via `poetry run streamlit run ui/app.py` to interact with the dashboard scaffold.

## Backtesting
See `notebooks/sample_backtest.ipynb` and `scripts/run_backtest_example.sh` for a minimal example of running the backtest engine.

## Contributing
- Format code with `ruff` and `black` (via `ruff format`).
- Maintain >80% coverage with `pytest --cov` (CI enforced).
- Use type hints everywhere and keep strategy logic deterministic for testing.

## Disclaimer
This repository is a scaffold and **not** ready for production trading without substantial development, validation, and regulatory compliance work.
