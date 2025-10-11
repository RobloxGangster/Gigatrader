"""Command line interface for Gigatrader orchestration."""

from __future__ import annotations

import argparse
import os
from typing import List

from services.runtime.logging import setup_logging


def _collect_env_errors() -> List[str]:
    errors: List[str] = []
    key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
    if not key or not secret:
        errors.append("missing_alpaca_credentials")
    return errors


def _strict_errors() -> List[str]:
    try:
        from services.runtime.runner import Runner
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency missing
        return [f"module_missing:{getattr(exc, 'name', 'unknown')}"]
    runner = Runner()
    return runner.readiness_errors(strict=True)


def _run_check(strict: bool) -> int:
    setup_logging()
    errors = _collect_env_errors()
    if strict:
        errors.extend(_strict_errors())
        # Deduplicate while preserving order
        seen = set()
        errors = [err for err in errors if not (err in seen or seen.add(err))]
    if errors:
        print("NOT READY: " + ", ".join(errors))
        return 1
    print("READY")
    return 0


def _run_service(demo: bool) -> None:
    if demo:
        os.environ.setdefault("RUN_MARKET", "false")
        os.environ.setdefault("RUN_SENTIMENT", "true")
        os.environ.setdefault("TRADING_MODE", "paper")
    from services.runtime.runner import main as run_main

    run_main()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gigatrader")
    sub = parser.add_subparsers(dest="cmd")

    run_parser = sub.add_parser("run", help="Start the orchestrator")
    run_parser.set_defaults(cmd="run")

    check_parser = sub.add_parser("check", help="Perform readiness checks")
    check_parser.add_argument("--strict", action="store_true", help="Verify external dependencies")
    check_parser.set_defaults(cmd="check")

    demo_parser = sub.add_parser("demo", help="Run demo mode without live market streaming")
    demo_parser.set_defaults(cmd="demo")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        _run_service(demo=False)
        return

    if args.cmd == "check":
        code = _run_check(strict=getattr(args, "strict", False))
        raise SystemExit(code)

    if args.cmd == "demo":
        _run_service(demo=True)
        return

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
