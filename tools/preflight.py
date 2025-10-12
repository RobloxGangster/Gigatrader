#!/usr/bin/env python3
import os, sys
req=["ALPACA_PAPER"]
missing=[k for k in req if not os.getenv(k)]
print("PREFLIGHT OK" if not missing else f"MISSING {missing}")
sys.exit(0 if not missing else 1)
