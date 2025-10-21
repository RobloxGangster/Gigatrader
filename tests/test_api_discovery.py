from ui.lib.api_client import discover_base_url, reset_discovery_cache


def test_discover_base_url_smoke(monkeypatch):
    monkeypatch.setenv("GIGAT_API_URL", "http://localhost:8000")
    reset_discovery_cache()
    base = discover_base_url()
    assert base.startswith("http://")
