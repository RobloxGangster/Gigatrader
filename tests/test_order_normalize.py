from ui.services.backend import _normalize_order_shape


def test_alpaca_new_maps_to_pending():
    raw = {
        "id": "abc",
        "client_order_id": "coid-1",
        "symbol": "AAPL",
        "side": "buy",
        "time_in_force": "day",
        "qty": "5",
        "filled_qty": "2",
        "status": "new",
        "created_at": "2025-10-15T20:00:00Z",
    }
    rec = _normalize_order_shape(raw)
    assert rec["status"] == "pending"
    assert rec["leaves_qty"] == 3.0
    assert rec["order_id"] == "abc"
    assert rec["tif"] == "day"
    assert rec["updated_at"] is not None
