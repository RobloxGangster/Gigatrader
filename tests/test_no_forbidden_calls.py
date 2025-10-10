from pathlib import Path

FORBIDDEN_CALL = "TradingClient.submit_order_async"


def test_no_direct_submit_order_async_usage():
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in repo_root.rglob("*.py"):
        if path.name == "test_no_forbidden_calls.py":
            continue
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN_CALL in text:
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"Forbidden call found in: {', '.join(offenders)}"
