from app.data.market import MockDataClient
from app.signals.signal_engine import SignalConfig, SignalEngine


def test_signal_engine_produces_candidates():
    client = MockDataClient()
    config = SignalConfig(top_n=5, enable_options=False)
    engine = SignalEngine(client, config=config)
    bundle = engine.produce()
    assert bundle.candidates
    for candidate in bundle.candidates:
        assert 0.0 <= candidate.confidence <= 2.0
