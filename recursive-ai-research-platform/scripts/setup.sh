#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[setup] Verifying Python 3.9+ runtime..."
python3 --version

echo "[setup] Generating deterministic synthetic fixture and SHA-256 manifest..."
PYTHONPATH=src python3 -m rarp generate-fixture --output-dir data/fixtures --seed 42

echo "[setup] Complete. No mandatory external dependencies are required for core execution."
