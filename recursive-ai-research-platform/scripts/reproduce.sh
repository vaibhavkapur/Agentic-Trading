#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f "data/fixtures/synthetic_multi_regime_equities_v1.manifest.json" ]; then
  bash scripts/setup.sh
fi

echo "[reproduce] Verifying deterministic replay reproducibility across clean runs..."
PYTHONPATH=src python3 -m rarp reproduce \
  --config-dir config \
  --manifest data/fixtures/synthetic_multi_regime_equities_v1.manifest.json \
  --output reports/reproducibility_report.json

echo "[reproduce] Report written to reports/reproducibility_report.json"
