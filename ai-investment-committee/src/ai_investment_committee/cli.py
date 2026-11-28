"""Command-line interface for running, approving, replaying, and evaluating deliberations."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .errors import CommitteeError
from .models import HumanApprovalRecord
from .service import InvestmentCommitteeService, load_json_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "committee_default.json"
DEFAULT_DB = PROJECT_ROOT / "reports" / "committee_deliberations.sqlite3"


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help="Path to versioned committee config JSON.",
    )
    common.add_argument(
        "--db",
        default=argparse.SUPPRESS,
        help="Path to SQLite deliberation store.",
    )

    parser = argparse.ArgumentParser(
        prog="ai-committee",
        description="AI Investment Committee prototype CLI (paper proposals only; no live execution).",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to versioned committee config JSON.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help="Path to SQLite deliberation store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", parents=[common], help="Run committee deliberation on a proposal JSON file.")
    run_p.add_argument("--proposal", required=True, help="Path to proposal JSON fixture.")

    app_p = sub.add_parser("approve", parents=[common], help="Record human approval or rejection bound to proposal hash.")
    app_p.add_argument("--decision-id", required=True)
    app_p.add_argument("--approval-id", required=True)
    app_p.add_argument("--proposal-id", required=True)
    app_p.add_argument("--proposal-hash", required=True)
    app_p.add_argument("--reviewer-id", required=True)
    app_p.add_argument("--decision", choices=["APPROVE_PAPER", "REJECT"], required=True)
    app_p.add_argument("--rationale", required=True)

    rep_p = sub.add_parser("replay", parents=[common], help="Replay a stored deliberation and verify determinism.")
    rep_p.add_argument("--decision-id", required=True)

    eval_p = sub.add_parser("evaluate", parents=[common], help="Evaluate dissent, citations, and cost for a decision.")
    eval_p.add_argument("--decision-id", required=True)

    sub.add_parser("list", parents=[common], help="List persisted deliberations in SQLite.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        service = InvestmentCommitteeService.from_config_path(
            config_path=args.config,
            db_path=args.db,
        )
        if args.command == "run":
            proposal_dict = load_json_file(args.proposal, label="proposal")
            trace = service.deliberate(proposal_dict)
            print(json.dumps(trace.model_dump(), indent=2, sort_keys=True))
            return 0

        if args.command == "approve":
            approval = HumanApprovalRecord(
                approval_id=args.approval_id,
                proposal_id=args.proposal_id,
                proposal_hash=args.proposal_hash,
                reviewer_id=args.reviewer_id,
                decision=args.decision,
                rationale=args.rationale,
                approved_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            updated = service.submit_human_approval(
                decision_id=args.decision_id,
                approval_input=approval,
            )
            print(json.dumps(updated.model_dump(), indent=2, sort_keys=True))
            return 0

        if args.command == "replay":
            result = service.replay(args.decision_id)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        if args.command == "evaluate":
            metrics = service.evaluate(args.decision_id)
            print(json.dumps(metrics.model_dump(), indent=2, sort_keys=True))
            return 0

        if args.command == "list":
            rows = service.store.list_deliberations()
            print(json.dumps(rows, indent=2, sort_keys=True))
            return 0

        return 2
    except CommitteeError as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
