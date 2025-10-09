.PHONY: setup lint typecheck test run-paper run-backtest report

setup:
poetry install

lint:
poetry run ruff check .

format:
poetry run ruff format .

typecheck:
poetry run mypy .

test:
poetry run pytest --cov=.

run-paper:
poetry run trade paper --config config.example.yaml

run-backtest:
poetry run trade backtest --config config.example.yaml

report:
poetry run trade report --run-id latest
