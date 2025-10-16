import os
from ui.utils.runtime import get_runtime_flags


def test_runtime_flags_detects_mock(monkeypatch):
    class Dummy: base_url = "http://127.0.0.1:8000"
    monkeypatch.setenv("MOCK_MODE", "true")
    flags = get_runtime_flags(Dummy())
    assert flags.mock_mode is True
    assert flags.base_url.endswith(":8000")
