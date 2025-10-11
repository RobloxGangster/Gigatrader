import os

import pytest

from services.market.store import TSStore


@pytest.mark.skipif(not os.getenv("TIMESCALE_URL"), reason="TIMESCALE_URL not set")
def test_schema_init() -> None:
    TSStore(os.getenv("TIMESCALE_URL", ""))
    assert True
