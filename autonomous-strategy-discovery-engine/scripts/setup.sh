#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[setup] Checking Python runtime..."
python3 --version

echo "[setup] Regenerating and verifying synthetic fixtures..."
PYTHONPATH="$ROOT/src" python3 "$ROOT/data/fixtures/generate_fixtures.py"

echo "[setup] Verifying fixture manifest integrity..."
PYTHONPATH="$ROOT/src" python3 -c "
from pathlib import Path
from asde.data.fixtures import load_dataset_from_manifest
ds = load_dataset_from_manifest(Path('data/fixtures/synthetic_equities_manifest.json'))
print(f'[setup] Verified dataset={ds.manifest.dataset_id} bars={ds.num_bars} symbols={ds.symbols} fp={ds.fingerprint[:16]}...')
"
echo "[setup] Complete."
