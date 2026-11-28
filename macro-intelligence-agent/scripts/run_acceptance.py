#!/usr/bin/env python3
"""Run gold-set evaluation and full acceptance validation, saving raw JSON evidence."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from macro_intelligence_agent.config import load_config
from macro_intelligence_agent.evaluator import evaluate_gold_set

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
REPORTS_DIR = PROJECT_ROOT / "reports"
CONFIG_PATH = PROJECT_ROOT / "config" / "default_config.json"


def main() -> int:
    # 1. Run full unittest discovery
    loader = unittest.TestLoader()
    suite = loader.discover(str(PROJECT_ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)
    if not test_result.wasSuccessful():
        return 1

    # 2. Evaluate against curated gold set
    cfg = load_config(CONFIG_PATH)
    eval_report = evaluate_gold_set(FIXTURES_DIR / "gold_set.json", config=cfg)
    eval_report["unit_and_integration_tests"] = {
        "tests_run": test_result.testsRun,
        "failures": len(test_result.failures),
        "errors": len(test_result.errors),
        "skipped": len(test_result.skipped),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "evaluation_results.json"
    out_path.write_text(json.dumps(eval_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    m = eval_report["metrics"]
    print("\n=== Curated Gold-Set Evaluation Summary (Synthetic Fixtures) ===")
    print(f"Cases Passed              : {m['cases_passed']}/{m['cases_total']}")
    print(f"Figure Exact-Match Rate   : {m['figure_exact_match_rate']} ({m['figure_exact_matches']})")
    print(f"Surprise Exact-Match Rate : {m['surprise_exact_match_rate']} ({m['surprise_exact_matches']})")
    print(f"Revision Exact-Match Rate : {m['revision_exact_match_rate']} ({m['revision_exact_matches']})")
    print(f"Citation Traceability     : {m['citation_traceability_rate']}")
    print(f"Abstention P / R / F1     : {m['abstention_precision']} / {m['abstention_recall']} / {m['abstention_f1']}")
    print(f"Embargo Leakage Count     : {m['embargo_leakage_count']}")
    print(f"False Fabrication Count   : {m['false_fabrication_count']}")
    print(f"Security Guardrail Pass   : {m['security_guardrail_pass_rate']}")
    print(f"Raw Report Written        : {out_path}")

    return 0 if (m["cases_passed"] == m["cases_total"] and m["embargo_leakage_count"] == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())
