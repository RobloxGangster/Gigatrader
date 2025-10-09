# Agent Guidelines

Welcome to the Gigatrader automated trading platform scaffold.

## Project Goals
- Deliver a production-grade, fully automated trading platform scaffold for US equities and equity options using Python 3.11 and the Alpaca (alpaca-py) ecosystem.
- Ensure the system defaults to paper trading, fails closed, and implements robust risk management, rate limiting, and kill-switch controls.
- Provide clear documentation, testing infrastructure, and a layman-friendly Streamlit UI for monitoring and control.

## Additional Context
- Adhere to the specified project layout: `/core`, `/data`, `/execution`, `/strategies`, `/risk`, `/backtest`, `/ui`, `/tests`, `/scripts`, plus top-level documentation files.
- Key abstractions include DataProvider, Broker, Strategy, RiskManager, and SlippageCostModel interfaces.
- Implement guardrails such as paper-first mode, global kill-switch, risk caps, options liquidity checks, central async rate-limited order queue, and `.env` based secrets management.
- Provide CLI commands (`trade backtest|paper|live|report|halt`), Streamlit dashboard features, and configuration presets (`safe`, `balanced`, `high_risk`).
- Ensure tooling support via Makefile, CI hooks (ruff, mypy, pytest), and example scripts/notebooks for backtesting and paper trading workflows.

Future contributors should reference this file for high-level objectives and constraints when making changes within the repository.
