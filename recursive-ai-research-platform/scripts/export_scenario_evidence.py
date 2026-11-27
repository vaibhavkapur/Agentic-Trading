"""Export structured evidence for all 6 required failure-path scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scenarios.test_required_scenarios import run_all_required_scenarios


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence = run_all_required_scenarios()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Scenario evidence exported to {args.output} (all_passed={evidence['all_passed']})")
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
