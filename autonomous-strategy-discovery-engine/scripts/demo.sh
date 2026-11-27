#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="$ROOT/reports/demo_run"
rm -rf "$OUT_DIR"

echo "[demo] Running deterministic discovery pipeline..."
PYTHONPATH="$ROOT/src" python3 -m asde.cli discover \
  --config "$ROOT/config/default_discovery.json" \
  --out "$OUT_DIR"

cp "$OUT_DIR/leaderboard.md" "$ROOT/reports/demo_leaderboard.md"
cp "$OUT_DIR/leaderboard.json" "$ROOT/reports/demo_report.json"

echo "[demo] Verifying exported strategy packages (if any)..."
if [ -d "$OUT_DIR/packages" ]; then
  for pkg in "$OUT_DIR"/packages/*; do
    if [ -d "$pkg" ]; then
      PYTHONPATH="$ROOT/src" python3 -m asde.cli verify-package --package "$pkg"
    fi
  done
fi

echo "[demo] Leaderboard written to reports/demo_leaderboard.md"
