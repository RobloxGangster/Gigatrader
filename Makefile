.PHONY: help bootstrap sync-deps run-paper run-ui run-market db-init check clean distclean install fmt lint test verify-all

VENVDIR ?= .venv
PY ?= $(VENVDIR)/bin/python
PIP ?= $(VENVDIR)/bin/pip
PIP_COMPILE ?= $(VENVDIR)/bin/pip-compile
DOTENV ?= .env

help:
	@echo "Targets:"
	@echo "  bootstrap  - Create venv, compile locks, install deps"
	@echo "  sync-deps  - Recompile requirements-*.txt from *.in"
	@echo "  run-paper  - Launch the paper runner"
	@echo "  check      - Ruff lint + pytest"
	@echo "  clean      - Remove build/test artifacts"
	@echo "  distclean  - Clean + remove venv"

$(VENVDIR)/bin/python:
	python3.11 -m venv $(VENVDIR)
	$(PIP) install --upgrade pip pip-tools

bootstrap: $(VENVDIR)/bin/python
	$(PIP_COMPILE) -q requirements-core.in -o requirements-core.txt
	$(PIP_COMPILE) -q requirements-dev.in -o requirements-dev.txt
	@if [ -f requirements-ml.in ]; then $(PIP_COMPILE) -q requirements-ml.in -o requirements-ml.txt; fi
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt
	@if [ -f requirements-ml.txt ]; then $(PIP) install -r requirements-ml.txt; fi
	cp -n .env.example .env 2>/dev/null || true
	cp -n config.example.yaml config.yaml 2>/dev/null || true
	@echo "Bootstrap complete. Activate with: . $(VENVDIR)/bin/activate"

sync-deps: $(VENVDIR)/bin/python
	$(PIP_COMPILE) -q requirements-core.in -o requirements-core.txt
	$(PIP_COMPILE) -q requirements-dev.in -o requirements-dev.txt
	@if [ -f requirements-ml.in ]; then $(PIP_COMPILE) -q requirements-ml.in -o requirements-ml.txt; fi

install: $(VENVDIR)/bin/python
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt

run-paper:
	ALPACA_PAPER=true TRADING_MODE=paper $(PY) -m cli.main run

run-market:
	$(PY) -m services.market.loop

db-init:
	$(PY) tools/db_init.py

run-ui:
	@set -a; [ -f $(DOTENV) ] && . $(DOTENV); set +a;
	$(PY) -m ui.app

fmt:
	$(PY) -m ruff format

lint:
	$(PY) -m ruff check

test:
	$(PY) -m pytest -q

check: fmt lint test

clean:
	rm -rf artifacts .pytest_cache build dist

distclean: clean
	rm -rf $(VENVDIR)

verify-all:
	$(PY) tools/verify_phase1.py
	$(PY) tools/verify_phase2.py
	$(PY) tools/verify_phase6.py
	$(PY) tools/verify_phase7.py
	$(PY) tools/verify_phase8.py
