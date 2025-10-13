from services.gateway.options import Intent, map_option_order


def test_long_only_mapping():
    bull = map_option_order(Intent("buy", "AAPL", 1))
    bear = map_option_order(Intent("sell", "AAPL", 1))
    assert bull["option_type"] == "call" and bull["side"] == "buy"
    assert bear["option_type"] == "put"  and bear["side"] == "buy"
