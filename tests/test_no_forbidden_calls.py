from __future__ import annotations

from pathlib import Path


FORBIDDEN = "TradingClient.submit_order_async"


def test_no_forbidden_submit_async_usage():
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    offenders: list[str] = []
    for path in src_dir.rglob("*.py"):
        if FORBIDDEN in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"Forbidden usage found: {offenders}"
