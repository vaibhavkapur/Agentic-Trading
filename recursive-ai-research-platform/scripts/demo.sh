#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f "data/fixtures/synthetic_multi_regime_equities_v1.manifest.json" ]; then
  bash scripts/setup.sh
fi

echo "[demo] Running auditable recursive AI research loop demo..."
PYTHONPATH=src python3 -m rarp demo \
  --config-dir config \
  --manifest data/fixtures/synthetic_multi_regime_equities_v1.manifest.json \
  --reports-dir reports \
  --reviewer-id reviewer_independent_lead

echo "[demo] Artifacts written to reports/demo_report.json and reports/demo_summary.md"
