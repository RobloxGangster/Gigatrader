import pathlib


def test_no_submit_order_async_on_client():
    text = ""
    for path in pathlib.Path("src").rglob("*.py"):
        text += path.read_text(encoding="utf-8", errors="ignore")
    assert "TradingClient.submit_order_async" not in text
