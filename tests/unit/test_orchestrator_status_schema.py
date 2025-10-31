from backend.routers.orchestrator import OrchestratorStatus


def test_orchestrator_status_allows_transition_field() -> None:
    stopping = OrchestratorStatus(state="stopped", running=False, transition="stopping")
    assert stopping.state == "stopped"
    assert stopping.transition == "stopping"
    assert stopping.running is False


def test_orchestrator_status_preserves_phase() -> None:
    payload = OrchestratorStatus(state="running", running=True, phase="waiting_market_open")
    assert payload.state == "running"
    assert payload.phase == "waiting_market_open"
