#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
mkdir -p .runtime
PYTHONPATH=src python3 -m finrag build
