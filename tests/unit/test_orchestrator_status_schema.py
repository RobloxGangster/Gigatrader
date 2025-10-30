from backend.routers.orchestrator import OrchestratorStatus


def test_orchestrator_status_accepts_transitional_states() -> None:
    idle = OrchestratorStatus(state="idle", running=False)
    assert idle.state == "idle"

    waiting = OrchestratorStatus(state="waiting_market_open", running=False)
    assert waiting.state == "waiting_market_open"

    stopping = OrchestratorStatus(state="stopping", running=False)
    assert stopping.state == "stopping"
