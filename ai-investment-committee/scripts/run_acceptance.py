#!/usr/bin/env python3
"""Run the full test suite and demo acceptance checks, emitting machine-readable evidence."""

from __future__ import annotations

import json
import platform
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
REPORTS_DIR = PROJECT_ROOT / "reports"
for p in (SRC_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from run_demo import run_demo


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(PROJECT_ROOT / "tests"), pattern="test_*.py")

    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)

    demo_summary = run_demo()

    test_report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "all_passed": result.wasSuccessful(),
        "duration_ms": duration_ms,
        "demo_summary_file": "reports/demo_run_summary.json",
        "baseline_comparison_file": "reports/baseline_comparison.json",
        "demo_runtime_config_id": demo_summary["runtime"]["config_id"],
    }
    (REPORTS_DIR / "test_results.json").write_text(
        json.dumps(test_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("\n--- Acceptance Run Summary ---")
    print(json.dumps(test_report, indent=2, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
