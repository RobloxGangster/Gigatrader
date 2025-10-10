.PHONY: help setup lock install fmt lint test run-paper
PY?=python
PIP?=pip
help:
	@echo "make setup | lock | install | fmt | lint | test | run-paper"
setup:
	$(PIP) install --upgrade pip pip-tools
lock:
	pip-compile -q requirements-core.in -o requirements-core.txt
	pip-compile -q requirements-dev.in -o requirements-dev.txt
	pip-compile -q requirements-ui.in -o requirements-ui.txt
	pip-compile -q requirements-ml.in -o requirements-ml.txt
install:
	$(PIP) install -r requirements-core.txt -r requirements-dev.txt
fmt:
	black app tests
lint:
	ruff check app tests
test:
	pytest -q tests/test_config.py tests/test_rate_limit.py
run-paper:
	$(PY) -m app.smoke.paper_stream
