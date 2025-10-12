Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

Quick start

Windows (cmd.exe)

```
scripts\setup_and_run.bat
```

macOS/Linux

```
bash scripts/setup_and_run.sh
```

Manual

```
make bootstrap
make run-paper
```

Env variables
See .env.example for required vars. Paper vs live is controlled by ALPACA_PAPER=true|false.

Safety
This step only uses paper endpoints by default. Live trading requires explicit env changes in later steps.

Secret Hygiene
--------------
Never commit .env. If accidentally committed, rotate keys and scrub history (e.g., BFG or git-filter-repo), then force-push.
