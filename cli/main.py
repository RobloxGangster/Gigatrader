import argparse, sys, os
from dotenv import load_dotenv

def main():
    ap=argparse.ArgumentParser(prog="gigatrader")
    sub=ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("check")
    sub.add_parser("demo")
    a=ap.parse_args()

    if a.cmd=="run":
        load_dotenv(override=False)
        from services.runtime.runner import main as run_main
        run_main()
    elif a.cmd=="check":
        miss=[k for k in ("APCA_API_KEY_ID","APCA_API_SECRET_KEY","APCA_API_BASE_URL") if not os.getenv(k)]
        print("READY" if not miss else f"NOT READY: missing {miss}")
        sys.exit(0 if not miss else 1)
    elif a.cmd=="demo":
        os.environ.setdefault("TRADING_MODE","paper")
        os.environ.setdefault("ALPACA_PAPER","true")
        from services.runtime.runner import main as run_main
        run_main()
    else:
        ap.print_help()

if __name__=="__main__":
    main()
