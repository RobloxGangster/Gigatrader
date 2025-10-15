from __future__ import annotations

from pathlib import Path

import pytest

from services.options.adapter import get_option_chain
from services.options.expected_move import expected_move


def test_expected_move_from_mock_chain(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    artifacts_root = Path(__file__).resolve().parent / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))

    chain = get_option_chain("SPY", "2023-08-01")
    move = expected_move(chain, "2023-08-01")

    assert move > 0
    assert move == pytest.approx(17.7, rel=0.05)
