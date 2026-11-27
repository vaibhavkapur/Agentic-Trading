"""Check committed fixtures, numerical evidence and the standalone dashboard."""
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sentiment.dashboard import render
from sentiment.engine import Engine
from sentiment.evaluation import evaluate


def check(expected, current, path):
    if isinstance(expected, float):
        equal = math.isclose(expected, current, rel_tol=1e-10, abs_tol=1e-12)
    elif isinstance(expected, list):
        equal = len(expected) == len(current)
        for i, (left, right) in enumerate(zip(expected, current)):
            check(left, right, f"{path}[{i}]")
    elif isinstance(expected, dict):
        equal = expected.keys() == current.keys()
        if equal:
            for key in expected:
                check(expected[key], current[key], path + "." + key)
    else:
        equal = expected == current
    if not equal:
        raise ValueError(f"Evidence mismatch at {path}")


fixtures = ROOT / "data/fixtures"
manifest = json.loads((fixtures / "manifest.json").read_text())
for filename, expected in manifest["sha256"].items():
    actual = hashlib.sha256((fixtures / filename).read_bytes()).hexdigest()
    check(expected, actual, filename)
report = evaluate(Engine.load(ROOT))
check(json.loads((ROOT / "reports/evaluation.json").read_text()), report, "evaluation")
check((ROOT / "reports/dashboard.html").read_text(), render(report)+"\n", "dashboard")
print("Fixture checksums, raw evaluation and dashboard reproduced.")
