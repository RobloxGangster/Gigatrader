from importlib import reload


def test_probe_fallback(monkeypatch):
    monkeypatch.delenv("STRICT_SIP", raising=False)
    import app.data.entitlement as entitlement
    reload(entitlement)
    entitlement.sip_entitled = lambda symbol="SPY": False  # type: ignore[assignment]
    import app.streaming as streaming
    reload(streaming)
    feed = streaming._select_feed_with_probe()
    assert str(feed).endswith("IEX")


def test_strict_sip(monkeypatch):
    monkeypatch.setenv("STRICT_SIP", "true")
    import app.data.entitlement as entitlement
    reload(entitlement)
    entitlement.sip_entitled = lambda symbol="SPY": False  # type: ignore[assignment]
    import app.streaming as streaming
    reload(streaming)
    try:
        streaming._select_feed_with_probe()
    except RuntimeError:
        return
    assert False, "STRICT_SIP should raise when SIP entitlement missing"
