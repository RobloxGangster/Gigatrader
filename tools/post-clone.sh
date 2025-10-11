#!/usr/bin/env bash
set -euo pipefail
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip pip-tools
make bootstrap
echo "Done. Run: make run-paper"
