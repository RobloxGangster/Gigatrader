from __future__ import annotations

from types import SimpleNamespace

from services.ops import alerts


class DummyResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


def test_send_slack_posts_json_payload(monkeypatch):
    payload = {}

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        payload.update({"url": url, "json": json, "timeout": timeout})
        return DummyResponse()

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setattr(alerts.requests, "post", fake_post)

    result = alerts.send_slack("hello world")

    assert result is True
    assert payload["url"] == "https://example.com/webhook"
    assert payload["json"] == {"text": "hello world"}
    assert payload["timeout"] == 5


def test_send_slack_gracefully_handles_missing_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    calls = SimpleNamespace(count=0)

    def fake_post(*_args, **_kwargs):
        calls.count += 1
        return DummyResponse()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    result = alerts.send_slack("ignored")

    assert result is False
    assert calls.count == 0
