"""Command-line interface for running sandboxed strategy evaluations and governance checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .contracts import DatasetManifest, StrategyProposal, StrategySpec
from .errors import SandboxError
from .registry import TrialRegistry
from .verifier import ExperimentEvaluator, load_sandbox_config


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise SandboxError(f"Input file not found: {path}", details={"path": str(path)})
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strategy-sandbox",
        description="Evaluate AI-generated trading strategy code in an isolated, resource-bounded paper sandbox.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run-trial", help="Evaluate a strategy proposal against an approved dataset.")
    run_p.add_argument("--config", type=Path, required=True, help="Path to SandboxConfig JSON.")
    run_p.add_argument("--spec", type=Path, required=True, help="Path to StrategySpec JSON.")
    run_p.add_argument("--dataset", type=Path, required=True, help="Path to DatasetManifest JSON.")
    run_p.add_argument("--proposal", type=Path, required=True, help="Path to StrategyProposal JSON.")
    run_p.add_argument("--reference", type=Path, default=None, help="Optional reference oracle JSON.")
    run_p.add_argument("--registry-dir", type=Path, default=None, help="Optional registry directory.")

    val_p = sub.add_parser("validate-config", help="Validate a SandboxConfig JSON file.")
    val_p.add_argument("--config", type=Path, required=True)

    rev_p = sub.add_parser("review", help="Record a human review bound to a trial's artifact hashes.")
    rev_p.add_argument("--registry-dir", type=Path, required=True)
    rev_p.add_argument("--trial-id", required=True)
    rev_p.add_argument("--review-id", required=True)
    rev_p.add_argument("--reviewer", required=True)
    rev_p.add_argument("--decision", choices=["APPROVE", "REJECT", "REQUEST_CHANGES"], required=True)
    rev_p.add_argument("--notes", default="")

    prom_p = sub.add_parser("promote", help="Attempt to promote a validated and reviewed trial.")
    prom_p.add_argument("--registry-dir", type=Path, required=True)
    prom_p.add_argument("--trial-id", required=True)
    prom_p.add_argument("--review-id", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate-config":
            cfg = load_sandbox_config(args.config)
            print(json.dumps({"valid": True, "config_version": cfg.config_version, "backend": cfg.sandbox_backend}))
            return 0

        if args.command == "run-trial":
            cfg = load_sandbox_config(args.config)
            spec = StrategySpec.model_validate(_load_json(args.spec))
            dataset = DatasetManifest.model_validate(_load_json(args.dataset))
            proposal = StrategyProposal.model_validate(_load_json(args.proposal))
            ref_expected = _load_json(args.reference) if args.reference else None

            evaluator = ExperimentEvaluator(config=cfg)
            trial = evaluator.evaluate(
                proposal=proposal,
                spec=spec,
                dataset=dataset,
                reference_expected=ref_expected,
            )
            if args.registry_dir is not None:
                reg = TrialRegistry(args.registry_dir)
                reg.record_trial(trial)

            print(
                json.dumps(
                    {
                        "trial_id": trial.trial_id,
                        "status": trial.status,
                        "code_sha256": trial.code_sha256,
                        "output_sha256": trial.output_sha256,
                        "checks": [
                            {"name": c.name, "passed": c.passed, "code": c.code}
                            for c in trial.checks
                        ],
                        "final_equity": trial.accounting.final_equity if trial.accounting else None,
                    },
                    indent=2,
                )
            )
            return 0 if trial.status == "PASSED" else 2

        if args.command == "review":
            reg = TrialRegistry(args.registry_dir)
            rec = reg.record_human_review(
                review_id=args.review_id,
                trial_id=args.trial_id,
                reviewer=args.reviewer,
                decision=args.decision,
                notes=args.notes,
            )
            print(json.dumps(rec.model_dump(mode="json"), indent=2))
            return 0

        if args.command == "promote":
            reg = TrialRegistry(args.registry_dir)
            dec = reg.promote_trial(args.trial_id, review_id=args.review_id)
            print(json.dumps(dec.model_dump(mode="json"), indent=2))
            return 0

        return 1
    except SandboxError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 3
    except Exception as exc:
        print(json.dumps({"error_code": "UNEXPECTED_ERROR", "message": str(exc)}), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
