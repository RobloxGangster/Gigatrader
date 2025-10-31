from __future__ import annotations

from dataclasses import dataclass

from core.runtime_flags import RuntimeFlags


@dataclass
class MockStream:
    name: str = "mock"

    def status(self) -> dict[str, str]:  # pragma: no cover - trivial accessor
        return {"status": "mock", "name": self.name}


@dataclass
class AlpacaStream:
    key: str | None
    secret: str | None
    base_url: str

    def status(self) -> dict[str, str]:  # pragma: no cover - trivial accessor
        return {"status": "alpaca", "base_url": self.base_url}


def make_stream(flags: RuntimeFlags) -> MockStream | AlpacaStream:
    broker_label = str(getattr(flags, "broker", "alpaca")).lower()
    use_mock_stream = bool(flags.mock_mode or broker_label == "mock")
    if use_mock_stream and not flags.mock_mode:
        raise RuntimeError("Live mode requested but stream would be mock")
    if use_mock_stream:
        return MockStream()
    return AlpacaStream(
        key=flags.alpaca_key,
        secret=flags.alpaca_secret,
        base_url=flags.alpaca_base_url,
    )
