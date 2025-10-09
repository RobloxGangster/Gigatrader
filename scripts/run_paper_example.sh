#!/usr/bin/env bash
set -euo pipefail

export LIVE_TRADING=false
poetry run trade paper --config config.example.yaml --risk-profile high_risk
