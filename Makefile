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
.PHONY: db-init run-market
db-init:
	python tools/db_init.py
run-market:
	python -m services.market.loop

.PHONY: verify-phase1
verify-phase1:
	python tools/verify_phase1.py

.PHONY: test-exec
test-exec:
	pytest -q tests/test_execution_engine.py

.PHONY: verify-phase2
verify-phase2:
	python tools/verify_phase2.py

.PHONY: run-sentiment test-sentiment
run-sentiment:
	uv run -p 3.11 python -c "import os; from services.sentiment.fetchers import StubFetcher; from services.sentiment.poller import Poller; from services.sentiment.store import SentiStore; symbols=[s.strip() for s in os.getenv('SYMBOLS','AAPL,MSFT,SPY').split(',') if s.strip()]; poller=Poller(store=SentiStore(), fetchers=[StubFetcher('stub')], symbols=symbols); print('Running one poll...'); print(poller.run_once())"

test-sentiment:
	uv run -p 3.11 --with pytest python -m pytest -q tests/test_sentiment_pipeline.py tests/test_filters_and_models.py
