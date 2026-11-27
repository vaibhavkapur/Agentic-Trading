#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
exec "${PYTHON:-python3}" -m unittest discover -s tests -v
