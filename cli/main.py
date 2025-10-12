"""Entry-point for Gigatrader command-line operations."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Sequence

from dotenv import load_dotenv

from services.runtime.logging import setup_logging
from services.runtime.runner import Runner

REQUIRED_ENV = ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")


def _load_env() -> None:
    load_dotenv(override=False)
    os.environ.setdefault("ALPACA_PAPER", "true")
    os.environ.setdefault("TRADING_MODE", "paper")


def _missing_env() -> list[str]:
    missing: list[str] = []
    for name in REQUIRED_ENV:
        if not os.getenv(name) and not os.getenv(name.replace("_ID", "")):
            missing.append(name)
    return missing


def cmd_check() -> int:
    _load_env()
    setup_logging()
    missing = _missing_env()
    if missing:
        print(f"NOT READY: missing {', '.join(missing)}")
        return 1
    print("READY")
    return 0


def cmd_run(mock_market: bool | None = None) -> int:
    _load_env()
    setup_logging()
    if mock_market is None:
        mock_market = os.getenv("MOCK_MARKET", "true").lower() in {"1", "true", "yes", "on"}
    os.environ["MOCK_MARKET"] = "true" if mock_market else "false"
    runner = Runner()
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:  # pragma: no cover - manual interruption
        return 130
    return 0


def cmd_demo() -> int:
    os.environ.setdefault("RUN_MARKET", "false")
    os.environ.setdefault("RUN_SENTIMENT", "true")
    os.environ.setdefault("SYMBOLS", "AAPL,MSFT,SPY")
    return cmd_run(mock_market=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gigatrader", description="Gigatrader control CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("check", help="Verify required environment variables are present")

    run_parser = sub.add_parser("run", help="Start the paper trading runner")
    run_parser.add_argument(
        "--no-mock-market",
        action="store_true",
        help="Disable the built-in mock market loop (requires live connectivity)",
    )

    sub.add_parser("demo", help="Launch the runner in demo mode with safe defaults")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "run":
        return cmd_run(mock_market=not getattr(args, "no_mock_market", False))
    if args.cmd == "demo":
        return cmd_demo()

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
