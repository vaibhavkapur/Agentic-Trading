"""Command-line interface for running, validating, replaying, and comparing evaluations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fin_eval.exceptions import FinEvalError
from fin_eval.runner import (
    ReplayBundle,
    load_dataset,
    load_fixture_store,
    load_injection_profile,
    load_model_config,
    load_report,
    replay_evaluation,
    run_evaluation,
)
from fin_eval.stats import compare_reports


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fin-eval",
        description="Financial Agent Evaluation Framework CLI (offline deterministic evaluation).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate
    p_val = sub.add_parser("validate", help="Validate dataset, fixtures, model config, and fault profiles.")
    p_val.add_argument("--dataset", type=Path, required=True)
    p_val.add_argument("--fixtures", type=Path, required=True)
    p_val.add_argument("--config", type=Path, required=True)
    p_val.add_argument("--faults", type=Path, default=None)
    p_val.add_argument("--include-held-out", action="store_true")

    # run
    p_run = sub.add_parser("run", help="Run an evaluation suite and emit versioned reports.")
    p_run.add_argument("--dataset", type=Path, required=True)
    p_run.add_argument("--fixtures", type=Path, required=True)
    p_run.add_argument("--config", type=Path, required=True)
    p_run.add_argument("--faults", type=Path, default=None)
    p_run.add_argument("--seeds", type=int, nargs="+", default=None)
    p_run.add_argument("--repeats", type=int, default=None, help="Generate N consecutive seeds starting from config.seed")
    p_run.add_argument("--baseline", type=Path, default=None)
    p_run.add_argument("--tolerance", type=float, default=0.02)
    p_run.add_argument("--out-dir", type=Path, default=None)
    p_run.add_argument("--include-held-out", action="store_true")

    # replay
    p_rep = sub.add_parser("replay", help="Deterministically re-grade a saved replay bundle.")
    p_rep.add_argument("--bundle", type=Path, required=True)
    p_rep.add_argument("--expected-report", type=Path, default=None)

    # compare
    p_cmp = sub.add_parser("compare", help="Compare two saved EvaluationReports.")
    p_cmp.add_argument("--current", type=Path, required=True)
    p_cmp.add_argument("--baseline", type=Path, required=True)
    p_cmp.add_argument("--tolerance", type=float, default=0.02)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            ds = load_dataset(args.dataset, allow_held_out=args.include_held_out)
            store = load_fixture_store(args.fixtures)
            cfg = load_model_config(args.config)
            prof = load_injection_profile(args.faults)
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "dataset_id": ds.dataset_id,
                        "tasks": len(ds.tasks),
                        "fixture_version": store.fixture_version,
                        "config_id": cfg.config_id,
                        "fault_profile": prof.profile_id,
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "run":
            ds = load_dataset(args.dataset, allow_held_out=args.include_held_out)
            store = load_fixture_store(args.fixtures)
            cfg = load_model_config(args.config)
            prof = load_injection_profile(args.faults)
            baseline = load_report(args.baseline) if args.baseline else None

            seeds = args.seeds
            if seeds is None and args.repeats is not None:
                if args.repeats < 1:
                    raise FinEvalError("--repeats must be >= 1")
                seeds = [cfg.seed + i for i in range(args.repeats)]

            report, _, _ = run_evaluation(
                dataset=ds,
                store=store,
                model_config=cfg,
                injection_profile=prof,
                seeds=seeds,
                baseline_report=baseline,
                baseline_tolerance=args.tolerance,
                out_dir=args.out_dir,
            )
            print(
                json.dumps(
                    {
                        "report_id": report.report_id,
                        "pass_rate": report.summary.pass_rate.model_dump(),
                        "mean_score": report.summary.mean_score.model_dump(),
                        "failure_type_counts": report.summary.failure_type_counts,
                        "total_cost_usd": report.summary.total_cost_usd,
                        "mean_latency_ms": report.summary.mean_latency_ms,
                        "baseline_within_tolerance": (
                            report.baseline_comparison.within_tolerance
                            if report.baseline_comparison
                            else None
                        ),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "replay":
            if not args.bundle.exists():
                raise FinEvalError(f"Replay bundle not found: {args.bundle}")
            bundle = ReplayBundle.model_validate_json(args.bundle.read_text(encoding="utf-8"))
            replayed = replay_evaluation(bundle)
            matches_expected = None
            if args.expected_report:
                expected = load_report(args.expected_report)
                matches_expected = replayed.report_id == expected.report_id
            print(
                json.dumps(
                    {
                        "replayed_report_id": replayed.report_id,
                        "pass_rate": replayed.summary.pass_rate.mean,
                        "mean_score": replayed.summary.mean_score.mean,
                        "matches_expected_report_id": matches_expected,
                    },
                    indent=2,
                )
            )
            if matches_expected is False:
                return 2
            return 0

        if args.command == "compare":
            current = load_report(args.current)
            baseline = load_report(args.baseline)
            diff = compare_reports(current, baseline, tolerance=args.tolerance)
            print(diff.model_dump_json(indent=2))
            return 0 if diff.within_tolerance else 2

    except FinEvalError as exc:
        print(f"ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
