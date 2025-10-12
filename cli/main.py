import argparse, sys, os
from dotenv import load_dotenv

def main():
    ap=argparse.ArgumentParser(prog="gigatrader")
    sub=ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("check")
    sub.add_parser("demo")
    a=ap.parse_args()

    paper_url="https://paper-api.alpaca.markets"
    if a.cmd=="run":
        load_dotenv(override=False)  # local .env, CI env wins
        os.environ.setdefault("APCA_API_BASE_URL", paper_url)
        from services.runtime.runner import main as run_main
        run_main()
    elif a.cmd=="check":
        checks={
            "APCA_API_KEY_ID": ("APCA_API_KEY_ID","ALPACA_API_KEY_ID","ALPACA_API_KEY"),
            "APCA_API_SECRET_KEY": ("APCA_API_SECRET_KEY","ALPACA_API_SECRET_KEY","ALPACA_API_SECRET"),
            "APCA_API_BASE_URL": ("APCA_API_BASE_URL","ALPACA_API_BASE_URL"),
        }
        missing=[]
        for primary, options in checks.items():
            if primary == "APCA_API_BASE_URL":
                if not any(os.getenv(opt) for opt in options):
                    os.environ.setdefault(primary, paper_url)
                continue
            if not any(os.getenv(opt) for opt in options):
                missing.append(primary)
        if missing:
            print("NOT READY: missing", missing); sys.exit(1)
        print("READY"); sys.exit(0)
    elif a.cmd=="demo":
        os.environ.setdefault("TRADING_MODE","paper")
        os.environ.setdefault("ALPACA_PAPER","true")
        os.environ.setdefault("APCA_API_BASE_URL", paper_url)
        from services.runtime.runner import main as run_main
        run_main()
    else:
        ap.print_help()

if __name__=="__main__":
    main()
