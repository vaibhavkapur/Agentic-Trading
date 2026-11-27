"""Command-line interface for the Autonomous Strategy Discovery Engine."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import List, Optional

from asde.export.packager import StrategyPackager, verify_package
from asde.export.review import ReviewDecision
from asde.pipeline import DiscoveryPipeline
from asde.types import format_utc


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cmd_discover(args: argparse.Namespace) -> int:
    pipeline = DiscoveryPipeline(project_root=_project_root())
    result = pipeline.run_from_config(
        config_path=Path(args.config),
        out_dir=Path(args.out),
        evaluate_locked_holdout_for_top=bool(args.verify_holdout),
    )
    print(json.dumps(
        {
            "run_id": result.run_id,
            "report_fingerprint": result.report_fingerprint,
            "health_metrics": result.health_metrics,
            "exported_packages": [str(p) for p in result.exported_packages],
            "out_dir": str(result.out_dir),
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    packager = StrategyPackager()
    checklist = {
        "verified_no_holdout_leakage": not args.incomplete_checklist,
        "verified_realistic_costs": not args.incomplete_checklist,
        "verified_multiple_testing_stats": not args.incomplete_checklist,
        "verified_turnover_and_drawdown": not args.incomplete_checklist,
        "verified_data_entitlements": not args.incomplete_checklist,
    }
    decision = ReviewDecision(
        reviewer_id=args.reviewer,
        reviewer_role=args.role,
        decision=args.decision,
        rationale=args.rationale,
        reviewed_at_utc=format_utc(datetime.now(timezone.utc)),
        checklist_verified=checklist,
        requested_target=args.target,
    )
    record = packager.apply_independent_review(
        package_dir=Path(args.package),
        decision=decision,
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


def cmd_verify_package(args: argparse.Namespace) -> int:
    manifest = verify_package(Path(args.package))
    print(json.dumps({"verified": True, "package_fingerprint": manifest["package_fingerprint"]}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asde",
        description="Autonomous Strategy Discovery Engine CLI (research & paper review only; execution disabled).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_disc = sub.add_parser("discover", help="Run deterministic strategy discovery pipeline.")
    p_disc.add_argument("--config", default=str(_project_root() / "config" / "default_discovery.json"))
    p_disc.add_argument("--out", default=str(_project_root() / "reports" / "demo_run"))
    p_disc.add_argument("--verify-holdout", action="store_true", help="Run one-time post-lock holdout check on top eligible candidate.")
    p_disc.set_defaults(func=cmd_discover)

    p_rev = sub.add_parser("review", help="Record an independent review decision on an exported package.")
    p_rev.add_argument("--package", required=True)
    p_rev.add_argument("--reviewer", required=True)
    p_rev.add_argument("--role", default="independent_quant_reviewer")
    p_rev.add_argument("--decision", choices=["APPROVE_PAPER_ONLY", "REJECT"], required=True)
    p_rev.add_argument("--rationale", required=True)
    p_rev.add_argument("--target", default="paper_sandbox")
    p_rev.add_argument("--incomplete-checklist", action="store_true")
    p_rev.set_defaults(func=cmd_review)

    p_ver = sub.add_parser("verify-package", help="Cryptographically verify an exported strategy package.")
    p_ver.add_argument("--package", required=True)
    p_ver.set_defaults(func=cmd_verify_package)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
