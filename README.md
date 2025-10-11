Trading Project – Step 0: Repo hardening & env bootstrap

This step pins Python, locks dependencies, defines a clean .env schema, adds a paper-trading smoke test that connects to the Alpaca Market Data WebSocket, and sets up CI + linting.

Quick start
git clone https://github.com/RobloxGangster/Gigatrader && cd Gigatrader
make bootstrap         # venv + lock + install + .env/config scaffold
make run-paper         # starts the paper runner


Advanced:

make sync-deps         # recompile lockfiles after editing requirements-*.in
make check             # lint + tests


Windows (PowerShell):

py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pip-tools
make bootstrap
make run-paper

Env variables
See .env.example for required vars. Paper vs live is controlled by ALPACA_PAPER=true|false.

Safety
This step only uses paper endpoints by default. Live trading requires explicit env changes in later steps.

Secret Hygiene
--------------
Never commit .env. If accidentally committed, rotate keys and scrub history (e.g., BFG or git-filter-repo), then force-push.
