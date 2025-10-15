from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

from core.kill_switch import KillSwitch


class FakeMetrics:
    def __init__(self) -> None:
        self.latency_p95 = 0.0
        self.reject_total = 0
        self.data_staleness = 0.0

    def snapshot(self):  # type: ignore[override]
        return {
            "order_latency_ms": {
                "p50": None,
                "p95": self.latency_p95,
                "count": 0,
                "latest": None,
            },
            "order_rejects_total": {
                "total": self.reject_total,
                "by_code": {},
            },
            "ws_reconnects_total": 0,
            "data_staleness_sec": self.data_staleness,
        }


def _reload_breakers(monkeypatch, kill_file, rejects_limit="5"):
    monkeypatch.setenv("MAX_REJECTS_PER_MIN", rejects_limit)
    monkeypatch.delenv("MAX_DATA_STALE_SEC", raising=False)
    monkeypatch.delenv("MAX_LATENCY_P95_MS", raising=False)
    monkeypatch.setenv("KILL_SWITCH_FILE", str(kill_file))
    monkeypatch.setenv("BREAKERS_CHECK_INTERVAL_SEC", "0.1")
    module = importlib.import_module("services.safety.breakers")
    return importlib.reload(module)


def test_reject_spike_trips_breaker_and_kill_switch(monkeypatch, tmp_path):
    kill_file = tmp_path / "kill"
    breakers = _reload_breakers(monkeypatch, kill_file)
    fake_metrics = FakeMetrics()
    monkeypatch.setattr(breakers, "metrics", fake_metrics)
    breakers._reset_for_tests()
    kill_switch = KillSwitch(path=kill_file)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    fake_metrics.reject_total = 0
    trips = breakers.enforce_breakers(now, kill_switch)
    assert trips == []
    assert not kill_switch.engaged_sync()

    fake_metrics.reject_total = 10
    trips = breakers.enforce_breakers(now + timedelta(seconds=30), kill_switch)
    assert trips == ["reject_spike"]
    assert kill_switch.engaged_sync()

    state = breakers.breaker_state()
    assert "reject_spike" in state["current"]
    assert state["last_trip"]["breakers"] == ["reject_spike"]
    assert state["observations"]["rejects_per_min"] >= 20.0


def test_health_and_metrics_report_breaker_state(monkeypatch, tmp_path):
    kill_file = tmp_path / "kill"
    breakers = _reload_breakers(monkeypatch, kill_file)
    fake_metrics = FakeMetrics()
    monkeypatch.setattr(breakers, "metrics", fake_metrics)
    breakers._reset_for_tests()
    kill_switch = KillSwitch(path=kill_file)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    fake_metrics.reject_total = 0
    breakers.enforce_breakers(now, kill_switch)
    fake_metrics.reject_total = 12
    breakers.enforce_breakers(now + timedelta(seconds=60), kill_switch)
    assert kill_switch.engaged_sync()

    server = importlib.reload(importlib.import_module("backend.server"))
    monkeypatch.setattr(server, "_kill_switch", kill_switch, raising=False)

    def _kill_switch_on_override() -> bool:
        return kill_switch.engaged_sync()

    monkeypatch.setattr(server, "_kill_switch_on", _kill_switch_on_override)
    assert server.breakers is breakers

    health = server.health()
    assert health["kill_switch"] is True
    assert "reject_spike" in health["breakers"]["current"]
    assert health["ok"] is False

    metrics_route = importlib.reload(importlib.import_module("backend.routes.metrics_extended"))
    monkeypatch.setattr(metrics_route, "metrics", fake_metrics)
    result = metrics_route.metrics_extended()
    assert result["kill_switch"]["engaged"] is True
    assert "reject_spike" in result["safety"]["current"]
