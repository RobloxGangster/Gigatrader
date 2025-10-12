.PHONY: bootstrap sync-deps run-paper run-api run-ui check verify-all clean distclean sanitize
VENVDIR ?= .venv
PY ?= $(VENVDIR)/bin/python
PIP ?= $(VENVDIR)/bin/pip

$(VENVDIR)/bin/python:
	python3 -m venv $(VENVDIR)
	$(PIP) install --upgrade pip pip-tools

bootstrap: $(VENVDIR)/bin/python
	$(VENVDIR)/bin/pip-compile -q requirements-core.in -o requirements-core.txt
	$(VENVDIR)/bin/pip-compile -q requirements-dev.in  -o requirements-dev.txt
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt
	@cp -n .env.example .env 2>/dev/null || true
	@cp -n config.example.yaml config.yaml 2>/dev/null || true
	@echo "Bootstrap complete."

sync-deps: $(VENVDIR)/bin/python
	$(VENVDIR)/bin/pip-compile -q requirements-core.in -o requirements-core.txt
	$(VENVDIR)/bin/pip-compile -q requirements-dev.in  -o requirements-dev.txt

run-paper:
	@set -a; [ -f .env ] && . .env; set +a; \
	$(PY) -m cli.main run

run-api:
	@set -a; [ -f .env ] && . .env; set +a; \
	$(PY) -m backend.api

run-ui:
	streamlit run ui/app.py

check:
	$(PY) -m cli.main check || true
	$(PY) -m ruff check services tools tests || true
	$(PY) -m pytest -q || true

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

sanitize:
	python tools/sanitize_repo.py

.PHONY: fix-shadowing
fix-shadowing:
	python tools/fix_shadowing.py
