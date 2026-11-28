#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== [1/4] Validating configuration ==="
PYTHONPATH=src python3 -m earnings_call_agent validate-config --config config/default.json

echo "=== [2/4] Running unit, integration, and boundary test suite ==="
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -v

echo "=== [3/4] Running reproducible end-to-end demo and replay verification ==="
python3 scripts/run_demo.py

echo "=== [4/4] Running gold fixture evaluation benchmark ==="
python3 scripts/run_eval.py

echo "=== All CI checks passed ==="
