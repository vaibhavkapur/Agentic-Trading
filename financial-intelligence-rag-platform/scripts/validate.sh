#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH=src
python3 -m unittest discover -v
python3 scripts/evaluate.py
python3 scripts/demo.py > /dev/null
