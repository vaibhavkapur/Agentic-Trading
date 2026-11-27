#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m uv venv --python 3.12 .venv
if python3 -m uv pip install --python .venv/bin/python -e ".[dev]" 2>/dev/null; then
  echo "Installed packages via uv."
else
  echo "Falling back to offline uv cache install..."
  python3 -m uv pip install --offline --python .venv/bin/python fastapi pydantic uvicorn httpx pytest ruff setuptools
  python3 -m uv pip install --offline --no-build-isolation --no-deps --python .venv/bin/python -e .
fi
echo "Setup complete. Activate with: source .venv/bin/activate"
