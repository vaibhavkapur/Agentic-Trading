#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[reproduce] Running discovery twice with identical seed & config..."
PYTHONPATH="$ROOT/src" python3 -m asde.cli discover \
  --config "$ROOT/config/default_discovery.json" \
  --out "$TMP_DIR/run_a" > "$TMP_DIR/out_a.json"

PYTHONPATH="$ROOT/src" python3 -m asde.cli discover \
  --config "$ROOT/config/default_discovery.json" \
  --out "$TMP_DIR/run_b" > "$TMP_DIR/out_b.json"

diff -u "$TMP_DIR/run_a/leaderboard.json" "$TMP_DIR/run_b/leaderboard.json"
diff -u "$TMP_DIR/run_a/trials.jsonl" "$TMP_DIR/run_b/trials.jsonl"
diff -u "$TMP_DIR/run_a/split_manifest.json" "$TMP_DIR/run_b/split_manifest.json"

echo "[reproduce] SUCCESS: leaderboard.json, trials.jsonl, and split_manifest.json are bit-for-bit identical."
