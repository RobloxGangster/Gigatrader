.PHONY: help bootstrap sync-deps run-paper check verify-all clean distclean
help:
	@echo "bootstrap | sync-deps | run-paper | check | verify-all | clean | distclean"

VENVDIR ?= .venv
PY ?= $(VENVDIR)/bin/python
PIP ?= $(VENVDIR)/bin/pip

$(VENVDIR)/bin/python:
	python3 -m venv $(VENVDIR)
	$(PIP) install --upgrade pip pip-tools

bootstrap: $(VENVDIR)/bin/python
	$(VENVDIR)/bin/pip-compile -q requirements-core.in -o requirements-core.txt
	$(VENVDIR)/bin/pip-compile -q requirements-dev.in  -o requirements-dev.txt
	-@[ -f requirements-ml.in ] && $(VENVDIR)/bin/pip-compile -q requirements-ml.in -o requirements-ml.txt || true
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt
	-@[ -f requirements-ml.txt ] && $(PIP) install -r requirements-ml.txt || true
	@cp -n .env.example .env 2>/dev/null || true
	@cp -n config.example.yaml config.yaml 2>/dev/null || true
	@echo "Bootstrap complete."

sync-deps: $(VENVDIR)/bin/python
	$(VENVDIR)/bin/pip-compile -q requirements-core.in -o requirements-core.txt
	$(VENVDIR)/bin/pip-compile -q requirements-dev.in  -o requirements-dev.txt
	-@[ -f requirements-ml.in ] && $(VENVDIR)/bin/pip-compile -q requirements-ml.in -o requirements-ml.txt || true

run-paper:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	$(PY) -m cli.main run

check:
	$(PY) -m cli.main check

verify-all:
	$(PY) tools/verify_phase1.py && \
	$(PY) tools/verify_phase2.py && \
	$(PY) tools/verify_phase6.py && \
	$(PY) tools/verify_phase7.py && \
	$(PY) tools/verify_phase8.py

clean:
	rm -rf artifacts .pytest_cache **/__pycache__ build dist

distclean: clean
	rm -rf $(VENVDIR)

.PHONY: quarantine-ai
quarantine-ai:
	python tools/quarantine_ai_docs.py
