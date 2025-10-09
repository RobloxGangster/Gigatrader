#!/usr/bin/env bash
set -euo pipefail

poetry run trade backtest --config config.example.yaml
