from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from services.risk.engine import Proposal, RiskManager
from services.risk.state import InMemoryState, Position


def setup_env() -> None:
    os.environ["RISK_PROFILE"] = "balanced"
    for key in [
        "DAILY_LOSS_LIMIT",
        "PER_TRADE_RISK_PCT",
        "MAX_POSITIONS",
        "MAX_NOTIONAL",
        "MAX_SYMBOL_NOTIONAL",
        "COOLDOWN_SEC",
        "KILL_SWITCH",
        "KILL_SWITCH_FILE",
        "OPTIONS_MIN_OI",
        "OPTIONS_MIN_VOLUME",
        "OPTIONS_DELTA_MIN",
        "OPTIONS_DELTA_MAX",
    ]:
        os.environ.pop(key, None)


def build_manager(state: InMemoryState) -> RiskManager:
    return RiskManager(state)


def test_equity_hook_used_when_available() -> None:
    setup_env()
    state = InMemoryState()
    state.account_equity = 200_000.0  # pretend live equity
    os.environ["PER_TRADE_RISK_PCT"] = "1.0"  # $2,000 risk budget with equity hook
    os.environ["MAX_NOTIONAL"] = "500000"
    os.environ["MAX_SYMBOL_NOTIONAL"] = "500000"
    manager = build_manager(state)

    decision = manager.pre_trade_check(
        Proposal("AAPL", "buy", 1_200, 100, est_sl=98)
    )  # risk/share = 2 -> max_qty = 1_000
    assert not decision.allow
    assert decision.reason == "per_trade_risk_exceeded"
    assert decision.max_qty is not None
    assert decision.max_qty <= 1_000.01


def test_fallback_to_max_notional_when_no_equity() -> None:
    setup_env()
    state = InMemoryState()
    state.account_equity = None
    os.environ["PER_TRADE_RISK_PCT"] = "1.0"
    os.environ["MAX_NOTIONAL"] = "100000"  # $1,000 risk budget fallback
    os.environ["MAX_SYMBOL_NOTIONAL"] = "1000000"
    manager = build_manager(state)

    decision = manager.pre_trade_check(
        Proposal("AAPL", "buy", 600, 100, est_sl=98)
    )  # risk/share = 2 -> max_qty = 500
    assert not decision.allow
    assert decision.reason == "per_trade_risk_exceeded"
    assert decision.max_qty is not None
    assert decision.max_qty <= 500.01


def test_kill_switch_env_blocks_proposals() -> None:
    setup_env()
    state = InMemoryState()
    os.environ["KILL_SWITCH"] = "true"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 1, 100))
    assert not decision.allow
    assert decision.reason == "kill_switch_active"


def test_kill_switch_file_blocks_proposals(tmp_path: Path) -> None:
    setup_env()
    state = InMemoryState()
    kill_file = tmp_path / "halt"
    kill_file.write_text("halt")
    os.environ["KILL_SWITCH_FILE"] = str(kill_file)
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 1, 100))
    assert not decision.allow
    assert decision.reason == "kill_switch_active"


def test_daily_loss_limit_blocks_when_breached() -> None:
    setup_env()
    state = InMemoryState()
    state.day_pnl = -2_000
    os.environ["DAILY_LOSS_LIMIT"] = "1500"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 1, 100))
    assert not decision.allow
    assert decision.reason == "daily_loss_limit_breached"


def test_max_positions_blocks_new_symbol() -> None:
    setup_env()
    state = InMemoryState()
    state.positions = {
        f"SYM{i}": Position(symbol=f"SYM{i}", qty=1, notional=1_000) for i in range(5)
    }
    os.environ["MAX_POSITIONS"] = "5"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("NEW", "buy", 1, 100))
    assert not decision.allow
    assert decision.reason == "max_positions_exceeded"


def test_max_symbol_notional_blocks_excess_concentration() -> None:
    setup_env()
    state = InMemoryState()
    state.positions = {"AAPL": Position("AAPL", qty=10, notional=12_000)}
    os.environ["MAX_SYMBOL_NOTIONAL"] = "15000"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 50, 100))
    assert not decision.allow
    assert decision.reason == "max_symbol_notional_exceeded"


def test_max_portfolio_notional_blocks_when_exceeded() -> None:
    setup_env()
    state = InMemoryState()
    state.portfolio_notional = 45_000
    os.environ["MAX_NOTIONAL"] = "50000"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 100, 200))
    assert not decision.allow
    assert decision.reason == "max_portfolio_notional_exceeded"


def test_cooldown_blocks_recent_trades() -> None:
    setup_env()
    state = InMemoryState()
    state.mark_trade("AAPL", when=time.time())
    os.environ["COOLDOWN_SEC"] = "300"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 1, 100))
    assert not decision.allow
    assert decision.reason == "cooldown_active"


def test_option_liquidity_checks() -> None:
    setup_env()
    state = InMemoryState()
    manager = build_manager(state)

    decision = manager.pre_trade_check(
        Proposal("AAPL2315C", "buy", 1, 5.0, is_option=True, delta=0.1),
        symbol_oi=100,
        symbol_vol=50,
    )
    assert not decision.allow
    assert decision.reason in {"options_min_oi_not_met", "options_delta_out_of_bounds"}

    decision = manager.pre_trade_check(
        Proposal("AAPL2315C", "buy", 1, 5.0, is_option=True, delta=0.5),
        symbol_oi=200,
        symbol_vol=50,
    )
    assert not decision.allow
    assert decision.reason == "options_min_volume_not_met"


def test_invalid_stop_denied() -> None:
    setup_env()
    state = InMemoryState()
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 10, 100, est_sl=100))
    assert not decision.allow
    assert decision.reason == "invalid_stop_for_risk"


def test_allows_when_within_limits() -> None:
    setup_env()
    state = InMemoryState()
    state.day_pnl = 0
    state.portfolio_notional = 10_000
    state.positions = {"AAPL": Position("AAPL", qty=10, notional=1_000)}
    state.mark_trade("AAPL", when=time.time() - 1_000)
    os.environ["MAX_NOTIONAL"] = "50000"
    os.environ["MAX_SYMBOL_NOTIONAL"] = "20000"
    os.environ["MAX_POSITIONS"] = "10"
    os.environ["COOLDOWN_SEC"] = "10"
    os.environ["PER_TRADE_RISK_PCT"] = "2.0"
    manager = build_manager(state)

    decision = manager.pre_trade_check(
        Proposal("AAPL", "buy", 10, 100, est_sl=95)
    )  # risk/share=5 -> max_qty=200 when fallback to max_notional=50k
    assert decision.allow
    assert decision.reason == "ok"


def test_risk_budget_zero_blocks() -> None:
    setup_env()
    state = InMemoryState()
    state.account_equity = 0
    os.environ["PER_TRADE_RISK_PCT"] = "0.0"
    manager = build_manager(state)

    decision = manager.pre_trade_check(Proposal("AAPL", "buy", 10, 100, est_sl=90))
    assert not decision.allow
    assert decision.reason == "per_trade_risk_exceeded"
    assert decision.max_qty == pytest.approx(0.0)
