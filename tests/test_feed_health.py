import datetime as dt

from pytest import approx

from app.data.quality import FeedHealth


def test_is_stale_after_threshold():
    health = FeedHealth()
    symbol = "AAPL"
    event_ts = dt.datetime(2024, 1, 1, 13, 30, tzinfo=dt.timezone.utc)
    ingest_ts = event_ts + dt.timedelta(seconds=0.2)
    health.note_event(symbol, event_ts, ingest_ts)

    now = event_ts + dt.timedelta(seconds=10)
    assert health.is_stale(symbol, now, 5) is True
    assert health.get_status(symbol) == "STALE"


def test_latency_percentiles():
    health = FeedHealth()
    base = dt.datetime(2024, 1, 1, 13, 30, tzinfo=dt.timezone.utc)
    latencies = [0.05, 0.1, 0.2, 0.4]
    for idx, latency in enumerate(latencies):
        event_ts = base + dt.timedelta(seconds=idx)
        ingest_ts = event_ts + dt.timedelta(seconds=latency)
        health.note_event("MSFT", event_ts, ingest_ts)

    summary = health.latency_summary("MSFT")
    assert summary["p50"] == approx(0.15, rel=1e-2)
    assert summary["p95"] == approx(0.37, rel=1e-2)
