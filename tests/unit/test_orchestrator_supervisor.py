from __future__ import annotations

from backend.services import orchestrator as orchestrator_mod
from backend.services.orchestrator import OrchestratorSupervisor
from core.kill_switch import KillSwitch


def test_safe_arm_trading_respects_violation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BROKER", "alpaca")
    monkeypatch.setenv("PROFILE", "paper")
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")

    kill_path = tmp_path / "ks.json"
    kill_switch = KillSwitch(kill_path)
    supervisor = OrchestratorSupervisor(kill_switch)
    try:
        kill_switch.engage_sync(reason="manual_stop")
        snapshot = supervisor.safe_arm_trading(requested_by="test")
        assert snapshot["engaged"] is False
        history = supervisor.kill_switch_history()
        assert history and history[0]["action"] == "reset"

        kill_switch.engage_sync(reason="risk:daily_loss_limit")
        blocked = supervisor.safe_arm_trading(requested_by="test")
        assert blocked["engaged"] is True
        history = supervisor.kill_switch_history()
        assert history[0]["action"] == "reset_blocked"
        status = supervisor.status()
        assert status["kill_switch_reason"] == "risk:daily_loss_limit"
        assert status["kill_switch_can_reset"] is False
    finally:
        orchestrator_mod._CURRENT_SUPERVISOR = None
