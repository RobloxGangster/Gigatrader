Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

Quick start

Create and activate a virtualenv.

Install pip-tools, compile lockfiles, then install deps:
pip install --upgrade pip pip-tools
pip-compile -q requirements-core.in -o requirements-core.txt
pip-compile -q requirements-dev.in -o requirements-dev.txt
pip-compile -q requirements-ui.in -o requirements-ui.txt
pip-compile -q requirements-ml.in -o requirements-ml.txt
pip install -r requirements-core.txt -r requirements-dev.txt

Copy env template and fill PAPER keys from Alpaca:
cp .env.example .env

Run smoke test (paper mode):
make run-paper # streams a few 1m bars for AAPL, MSFT, SPY then exits

Env variables
See .env.example for required vars. Paper vs live is controlled by ALPACA_PAPER=true|false.

Safety
This step only uses paper endpoints by default. Live trading requires explicit env changes in later steps.

Secret Hygiene
--------------
Never commit .env. If accidentally committed, rotate keys and scrub history (e.g., BFG or git-filter-repo), then force-push.
