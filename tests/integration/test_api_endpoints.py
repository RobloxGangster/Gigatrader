import os, requests, pytest

API = f"http://127.0.0.1:{os.getenv('GT_API_PORT','8000')}"


@pytest.mark.usefixtures("server_stack")
def test_health_ok():
    r = requests.get(f"{API}/health", timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert "status" in j
    assert "mock_mode" in j  # backend exposes this in /health


@pytest.mark.usefixtures("server_stack")
def test_orders_positions_ok_or_empty():
    r1 = requests.get(f"{API}/orders?live=true", timeout=10)
    r2 = requests.get(f"{API}/positions?live=true", timeout=10)
    assert r1.status_code in (200, 404)
    assert r2.status_code in (200, 404)


@pytest.mark.usefixtures("server_stack")
def test_account_skipped_in_mock(require_mock):
    r = requests.get(f"{API}/alpaca/account", timeout=10)
    assert r.status_code in (200, 404)  # mock may return 200 with mock flag, or route hidden


@pytest.mark.usefixtures("server_stack")
@pytest.mark.paper_only
def test_account_in_paper(require_paper):
    r = requests.get(f"{API}/alpaca/account", timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert any(k in j for k in ("portfolio_value","equity","buying_power"))
