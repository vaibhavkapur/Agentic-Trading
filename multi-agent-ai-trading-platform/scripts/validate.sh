#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p reports/evidence

echo "=== 1. Ruff Lint ==="
.venv/bin/ruff check src tests scripts

echo "=== 2. Pytest Suite (Unit + Integration + Failure Scenarios) ==="
.venv/bin/pytest -v | tee reports/evidence/pytest_output.txt

echo "=== 3. Reproducible Paper Trading Demo ==="
.venv/bin/python scripts/demo.py

echo "=== 4. 7-Scenario + Partial-Fill + Restart Failure Drill ==="
.venv/bin/python scripts/scenario_drill.py

echo "=== All validation checks passed! ==="
