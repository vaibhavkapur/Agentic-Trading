#!/usr/bin/env python3
"""Run the gold evaluation benchmark and persist machine-readable results to reports/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from earnings_call_agent.contracts import AgentConfig
from earnings_call_agent.evaluation import evaluate_gold_suite, load_json_file


def main() -> int:
    config = AgentConfig.from_file(str(PROJECT_ROOT / "config" / "default.json"))
    eval_cfg = load_json_file(str(PROJECT_ROOT / "config" / "eval.json"))
    suite = load_json_file(str(PROJECT_ROOT / "data" / "fixtures" / "gold_eval_suite.json"))

    result = evaluate_gold_suite(suite, config, eval_cfg)
    out_path = PROJECT_ROOT / "reports" / "eval_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    m = result["summary_metrics"]
    print(
        f"Gold Eval Complete | F1={m['extraction_f1']:.4f} "
        f"(P={m['extraction_precision']:.4f}, R={m['extraction_recall']:.4f}) | "
        f"CitationValidity={m['citation_validity_rate']:.4f} | "
        f"GuidanceAcc={m['guidance_accuracy']:.4f} | "
        f"QA/Abstention={m['qa_and_abstention_accuracy']:.4f} | "
        f"InjectionDefense={m['injection_detection_accuracy']:.4f}"
    )
    print(f"Saved report to: {out_path}")
    return 0 if result["all_targets_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
