#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip pip-tools
pip-compile -q requirements-core.in -o requirements-core.txt
pip-compile -q requirements-dev.in -o requirements-dev.txt
[ -f requirements-ml.in ] && pip-compile -q requirements-ml.in -o requirements-ml.txt
pip install -r requirements-core.txt -r requirements-dev.txt
[ -f requirements-ml.txt ] && pip install -r requirements-ml.txt
cp -n .env.example .env 2>/dev/null || true
python -m cli.main run
