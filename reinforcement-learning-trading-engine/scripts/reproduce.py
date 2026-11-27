#!/usr/bin/env python3
"""Replay the bundled evaluation in isolation and compare the research outputs."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reports/reference"


def main():
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "run"
        subprocess.run([sys.executable, str(ROOT / "scripts/demo.py"), "--out", str(out)], check=True)
        for name in ("config.json", "decisions.csv", "metrics.json", "summary.json", "report.md"):
            if (REFERENCE / name).read_bytes() != (out / name).read_bytes():
                raise SystemExit(f"Reproduction mismatch: {name}")
        for path in sorted(REFERENCE.glob("*policy*.json")):
            actual = json.loads((out / path.name).read_text())
            expected = json.loads(path.read_text())
            for payload in (actual, expected):
                for key in ("platform", "python"):
                    payload["provenance"].pop(key)
            if actual != expected:
                raise SystemExit(f"Reproduction mismatch: {path.name}")
    print("Matched reference decisions, metrics, report and exported policies.")


if __name__ == "__main__":
    main()
