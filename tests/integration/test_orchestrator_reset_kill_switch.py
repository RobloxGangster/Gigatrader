from fastapi.testclient import TestClient

from backend import api as backend_api
from backend.routers import orchestrator as orchestrator_router


class _StubOrchestrator:
    def __init__(self, snapshot: dict[str, object]):
        self._snapshot = snapshot
        self.reset_calls: list[str] = []

    def reset_kill_switch(self, *, requested_by: str) -> None:  # noqa: D401 - test stub
        self.reset_calls.append(requested_by)

    def status(self) -> dict[str, object]:  # noqa: D401 - test stub
        return dict(self._snapshot)


def test_reset_kill_switch_allows_transitional_state(monkeypatch):
    orchestrator_snapshot = {
        "state": "stopping",
        "running": False,
        "kill_switch_engaged": False,
        "kill_switch": "Standby",
        "uptime_secs": 1.5,
        "restart_count": 2,
    }
    stub = _StubOrchestrator(orchestrator_snapshot)

    monkeypatch.setattr(orchestrator_router, "get_orchestrator", lambda: stub)
    monkeypatch.setattr(
        orchestrator_router.orchestrator_manager,
        "get_status",
        lambda: {"state": "stopping", "thread_alive": True},
    )

    client = TestClient(backend_api.app)
    response = client.post("/orchestrator/reset_kill_switch")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "stopped"
    assert payload["transition"] == "stopping"
    assert payload["kill_switch_engaged"] is False
    assert stub.reset_calls == ["api.reset"]
