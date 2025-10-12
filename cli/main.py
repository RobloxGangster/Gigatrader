import argparse, sys, os
from dotenv import load_dotenv
from services.runtime.runner import Runner
from services.runtime.logging import setup_logging

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
        setup_logging()
        missing=[]
        for k in ["ALPACA_API_KEY_ID","ALPACA_API_SECRET_KEY"]:
            if not os.getenv(k) and not os.getenv(k.replace("_ID","")):
                missing.append(k)
        print("READY" if not missing else f"NOT READY: missing {missing}")
        sys.exit(0 if not missing else 1)
    elif a.cmd=="demo":
        os.environ.setdefault("RUN_MARKET","false")
        os.environ.setdefault("RUN_SENTIMENT","true")
        os.environ.setdefault("TRADING_MODE","paper")
        from services.runtime.runner import main as run_main
        run_main()
    else:
        ap.print_help()

if __name__=="__main__":
    main()
