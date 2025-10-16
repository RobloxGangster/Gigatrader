from ui.services.backend import _normalize_order_shape


def test_alpaca_to_ui_mapping_and_leaves_qty():
    raw = {
        "id": "ord-1",
        "client_order_id": "coid-1",
        "symbol": "AAPL",
        "side": "buy",
        "time_in_force": "day",
        "qty": "5",
        "filled_qty": "2",
        "status": "new",
        "created_at": "2025-01-01T10:00:00Z",
    }
    rec = _normalize_order_shape(raw)
    assert rec["order_id"] == "ord-1"
    assert rec["tif"] == "day"
    assert rec["status"] in {"pending","working","filled","cancelled","rejected"}
    assert rec["leaves_qty"] == 3.0
    assert rec["updated_at"]
