#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p reports

if [ ! -f "data/fixtures/synthetic_multi_regime_equities_v1.manifest.json" ]; then
  bash scripts/setup.sh
fi

echo "[validate] Running unit, integration, and scenario test suites..."
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -v 2>&1 | tee reports/test_report.txt

echo "[validate] Exporting structured scenario verification evidence..."
PYTHONPATH=src:tests python3 scripts/export_scenario_evidence.py --output reports/scenario_evidence.json

echo "[validate] All validation checks passed."
