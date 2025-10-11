.PHONY: help bootstrap sync-deps run-paper run-ui check clean distclean
help:
	@echo "Targets:"
	@echo "  bootstrap - Create venv, compile locks, install"
	@echo "  sync-deps - Recompile lockfiles from *.in"
	@echo "  run-paper - Run paper runner (loads .env)"
	@echo "  run-ui - Run UI dev server (optional)"
	@echo "  check - Lint + unit tests (quick)"
	@echo "  clean - Remove build artifacts"
	@echo "  distclean - clean + .venv"

VENVDIR ?= .venv
PY ?= $(VENVDIR)/bin/python
PIP ?= $(VENVDIR)/bin/pip
DOTENV ?= .env

$(VENVDIR)/bin/python:
	python3.11 -m venv $(VENVDIR)
	$(PIP) install --upgrade pip pip-tools

bootstrap: $(VENVDIR)/bin/python
	$(VENVDIR)/bin/pip-compile -q requirements-core.in -o requirements-core.txt
	$(VENVDIR)/bin/pip-compile -q requirements-dev.in -o requirements-dev.txt
	-@[ -f requirements-ui.in ] && $(VENVDIR)/bin/pip-compile -q requirements-ui.in -o requirements-ui.txt || true
	-@[ -f requirements-ml.in ] && $(VENVDIR)/bin/pip-compile -q requirements-ml.in -o requirements-ml.txt || true
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt
	-@[ -f requirements-ui.txt ] && $(PIP) install -r requirements-ui.txt || true
	-@[ -f requirements-ml.txt ] && $(PIP) install -r requirements-ml.txt || true
	@cp -n .env.example .env 2>/dev/null || true
	@cp -n config.example.yaml config.yaml 2>/dev/null || true
	@echo "Bootstrap complete."

sync-deps: $(VENVDIR)/bin/python
	$(VENVDIR)/bin/pip-compile -q requirements-core.in -o requirements-core.txt
	$(VENVDIR)/bin/pip-compile -q requirements-dev.in -o requirements-dev.txt
	-@[ -f requirements-ui.in ] && $(VENVDIR)/bin/pip-compile -q requirements-ui.in -o requirements-ui.txt || true
	-@[ -f requirements-ml.in ] && $(VENVDIR)/bin/pip-compile -q requirements-ml.in -o requirements-ml.txt || true

run-paper:
	@set -a; [ -f $(DOTENV) ] && . $(DOTENV); set +a;
	$(PY) -m cli.main run

run-ui:
	@set -a; [ -f $(DOTENV) ] && . $(DOTENV); set +a;
	$(PY) -m ui.app

check:
	$(PY) -m ruff check services tests tools || true
	$(PY) -m pytest -q

clean:
	rm -rf artifacts .pytest_cache **/pycache build dist

distclean: clean
	rm -rf $(VENVDIR)

.PHONY: setup lock install fmt lint test
setup: bootstrap
lock: sync-deps
install:
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt
fmt:
	$(PY) -m black app tests
lint:
	$(PY) -m ruff check app tests
test:
	$(PY) -m pytest -q tests/test_config.py tests/test_rate_limit.py

.PHONY: db-init run-market
db-init:
	$(PY) tools/db_init.py
run-market:
	$(PY) -m services.market.loop

.PHONY: verify-phase1
verify-phase1:
	$(PY) tools/verify_phase1.py

.PHONY: test-exec
test-exec:
	$(PY) -m pytest -q tests/test_execution_engine.py

.PHONY: verify-phase2
verify-phase2:
	$(PY) tools/verify_phase2.py

.PHONY: run-sentiment test-sentiment
run-sentiment:
	uv run -p 3.11 python -c "import os; from services.sentiment.fetchers import StubFetcher; from services.sentiment.poller import Poller; from services.sentiment.store import SentiStore; symbols=[s.strip() for s in os.getenv('SYMBOLS','AAPL,MSFT,SPY').split(',') if s.strip()]; poller=Poller(store=SentiStore(), fetchers=[StubFetcher('stub')], symbols=symbols); print('Running one poll...'); print(poller.run_once())"

test-sentiment:
	uv run -p 3.11 --with pytest python -m pytest -q tests/test_sentiment_pipeline.py tests/test_filters_and_models.py

.PHONY: test-strategy
test-strategy:
	$(PY) -m pytest -q tests/test_strategy_engine.py

.PHONY: verify-phase6
verify-phase6:
	$(PY) tools/verify_phase6.py

.PHONY: run verify-phase7 test-runner
run:
	$(PY) -m cli.main run
verify-phase7:
	$(PY) tools/verify_phase7.py
test-runner:
	$(PY) -m pytest -q tests/test_runner_cli.py

.PHONY: sim verify-phase8 test-sim
sim:
	$(PY) -m services.sim.run

verify-phase8:
	$(PY) tools/verify_phase8.py

test-sim:
	$(PY) -m pytest -q tests/test_sim_smoke.py
