#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

export PYTHONPATH="${PROJECT_ROOT}/src"

echo "[1/4] Running unit, integration, security, and operational tests..."
python3 -m unittest discover -s tests -p "test_*.py" -v

echo "[2/4] Running reproducible end-to-end demo..."
python3 scripts/run_demo.py

echo "[3/4] Running curated gold-set acceptance evaluation..."
python3 scripts/run_acceptance.py

echo "[4/4] Verifying CLI smoke invocation..."
python3 -m macro_intelligence_agent evaluate \
  --gold-set data/fixtures/gold_set.json \
  --config config/default_config.json > /dev/null

echo "CI validation passed."
