"""Command-line interface for the Macro Intelligence Agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional

from .archive import ReleaseArchive
from .config import load_config
from .errors import MacroAgentError
from .evaluator import evaluate_gold_set
from .service import MacroIntelligenceService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macro-agent",
        description="Revision-aware macro release and central bank intelligence prototype (offline).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser("brief", help="Generate a publication-gated scenario brief.")
    p_brief.add_argument("--fixture", required=True, help="Path to release/consensus fixture JSON.")
    p_brief.add_argument("--series-group", required=True, help="Target series_group to analyze.")
    p_brief.add_argument(
        "--as-of",
        required=True,
        help="Historical publication gate cutoff in UTC ISO-8601 (e.g. 2025-05-13T13:00:00Z).",
    )
    p_brief.add_argument("--config", default=None, help="Optional JSON config file path.")
    p_brief.add_argument("--db", default=":memory:", help="SQLite archive path (default :memory:).")
    p_brief.add_argument("--output", default=None, help="Optional file path to write JSON result.")

    p_eval = sub.add_parser("evaluate", help="Evaluate against curated gold set.")
    p_eval.add_argument("--gold-set", required=True, help="Path to gold_set.json.")
    p_eval.add_argument("--config", default=None, help="Optional JSON config file path.")
    p_eval.add_argument("--output", default=None, help="Optional file path to write JSON report.")

    p_replay = sub.add_parser("replay", help="Replay a persisted run_id from SQLite archive.")
    p_replay.add_argument("--db", required=True, help="SQLite archive path.")
    p_replay.add_argument("--run-id", required=True, help="Recorded run_id to replay.")
    p_replay.add_argument("--config", default=None, help="Optional JSON config file path.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command == "brief":
            with ReleaseArchive(args.db) as archive:
                archive.load_fixture_file(args.fixture)
                service = MacroIntelligenceService(archive=archive, config=cfg)
                result = service.generate_brief(
                    series_group=args.series_group,
                    as_of_utc=args.as_of,
                )
            payload = json.dumps(result.to_dict(), indent=2, sort_keys=True)
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(payload + "\n", encoding="utf-8")
            else:
                print(payload)
            return 0

        if args.command == "evaluate":
            report = evaluate_gold_set(args.gold_set, config=cfg)
            payload = json.dumps(report, indent=2, sort_keys=True)
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(payload + "\n", encoding="utf-8")
            else:
                print(payload)
            return 0 if report["metrics"]["cases_passed"] == report["metrics"]["cases_total"] else 2

        if args.command == "replay":
            with ReleaseArchive(args.db) as archive:
                service = MacroIntelligenceService(archive=archive, config=cfg)
                matched, details = service.replay_run(args.run_id)
            print(json.dumps(details, indent=2, sort_keys=True))
            return 0 if matched else 3

        return 1
    except MacroAgentError as exc:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
