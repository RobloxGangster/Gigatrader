import argparse
import os
import sys

from dotenv import load_dotenv
from services.runtime.logging import setup_logging
from services.runtime.runner import Runner


def main() -> None:
    parser = argparse.ArgumentParser(prog="gigatrader")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("check")
    sub.add_parser("demo")
    args = parser.parse_args()

    if args.cmd == "run":
        load_dotenv(override=False)
        from services.runtime.runner import main as run_main

        run_main()
    elif args.cmd == "check":
        setup_logging()
        missing = []
        fallbacks = {
            "ALPACA_API_KEY_ID": "ALPACA_API_KEY",
            "ALPACA_API_SECRET_KEY": "ALPACA_API_SECRET",
        }
        for key, fallback in fallbacks.items():
            if not os.getenv(key) and not os.getenv(fallback):
                missing.append(key)
        if missing:
            print(f"NOT READY: missing env {missing}")
            sys.exit(1)
        try:
            Runner()
        except Exception as exc:  # pragma: no cover - defensive readiness check
            print(f"NOT READY: runner init failed: {exc}")
            sys.exit(1)
        print("READY")
        sys.exit(0)
    elif args.cmd == "demo":
        os.environ.setdefault("RUN_MARKET", "false")
        os.environ.setdefault("RUN_SENTIMENT", "true")
        os.environ.setdefault("TRADING_MODE", "paper")
        from services.runtime.runner import main as run_main

        run_main()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
