Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

## Quick start
```
# one time
make bootstrap
# run (paper)
make run-paper
```

## Verify locally (mirrors CI)
```
make verify-all
```

Env variables
See .env.example for required vars. Paper vs live is controlled by ALPACA_PAPER=true|false
and TRADING_MODE=paper|live (defaults favour paper).

Safety
This step only uses paper endpoints by default. Live trading requires explicit env changes in later steps.

Secret Hygiene
--------------
Never commit .env. If accidentally committed, rotate keys and scrub history (e.g., BFG or git-filter-repo), then force-push.
