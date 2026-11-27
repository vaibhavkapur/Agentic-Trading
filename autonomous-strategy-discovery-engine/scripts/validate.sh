#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[validate] Running unit, integration, and scenario test suite..."
PYTHONPATH="$ROOT/src:$ROOT" python3 -m unittest discover -s "$ROOT/tests" -p "test_*.py" -v

echo "[validate] Recording structured scenario verification evidence..."
PYTHONPATH="$ROOT/src:$ROOT" python3 -c "
import json
from pathlib import Path
from tests.scenarios.test_required_scenarios import run_all_scenarios_with_evidence

evidence = run_all_scenarios_with_evidence()
assert evidence['all_passed'], 'Not all required scenarios passed!'
out = Path('reports/scenario_evidence.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(f'[validate] Wrote scenario evidence to {out} (all_passed={evidence[\"all_passed\"]})')
"
echo "[validate] All checks passed."
