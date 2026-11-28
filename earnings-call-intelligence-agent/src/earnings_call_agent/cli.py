"""Command-line interface for analyzing transcripts, replaying runs, and running evaluations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .contracts import AgentConfig, EarningsCallAgentError
from .evaluation import evaluate_gold_suite, load_json_file
from .ingestion import load_transcript_file
from .pipeline import analyze_transcript, replay_and_verify


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="earnings-call-agent",
        description="Verifiable Earnings Call Intelligence Agent CLI (research prototype; no trade execution).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze a transcript JSON file.")
    p_analyze.add_argument("--input", required=True, help="Path to transcript JSON file.")
    p_analyze.add_argument(
        "--config",
        default=str(_default_project_root() / "config" / "default.json"),
        help="Path to agent config JSON file.",
    )
    p_analyze.add_argument("--as-of", default=None, help="Explicit UTC as_of_timestamp.")
    p_analyze.add_argument("--output", default=None, help="Optional path to write JSON report.")

    p_replay = sub.add_parser("replay", help="Replay an analysis and verify deterministic digest.")
    p_replay.add_argument("--input", required=True, help="Path to transcript JSON file.")
    p_replay.add_argument(
        "--config",
        default=str(_default_project_root() / "config" / "default.json"),
        help="Path to agent config JSON file.",
    )
    p_replay.add_argument("--as-of", default=None, help="Explicit UTC as_of_timestamp.")
    p_replay.add_argument("--expected-digest", default=None, help="Expected logical digest.")

    p_eval = sub.add_parser("evaluate", help="Run gold fixture evaluation suite.")
    p_eval.add_argument(
        "--suite",
        default=str(_default_project_root() / "data" / "fixtures" / "gold_eval_suite.json"),
        help="Path to gold evaluation suite JSON.",
    )
    p_eval.add_argument(
        "--config",
        default=str(_default_project_root() / "config" / "default.json"),
        help="Path to agent config JSON.",
    )
    p_eval.add_argument(
        "--eval-config",
        default=str(_default_project_root() / "config" / "eval.json"),
        help="Path to evaluation config JSON.",
    )
    p_eval.add_argument("--output", default=None, help="Optional path to write evaluation JSON.")

    p_val = sub.add_parser("validate-config", help="Validate an agent configuration file.")
    p_val.add_argument("--config", required=True, help="Path to agent config JSON.")

    args = parser.parse_args(argv)

    try:
        if args.command == "validate-config":
            cfg = AgentConfig.from_file(args.config)
            print(json.dumps({"valid": True, "config_digest": cfg.digest()}, indent=2))
            return 0

        if args.command == "analyze":
            cfg = AgentConfig.from_file(args.config)
            raw = load_transcript_file(args.input)
            report = analyze_transcript(raw, cfg, as_of_timestamp=args.as_of)
            payload = json.dumps(report.to_dict(), indent=2)
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(payload + "\n", encoding="utf-8")
            else:
                print(payload)
            return 0

        if args.command == "replay":
            cfg = AgentConfig.from_file(args.config)
            raw = load_transcript_file(args.input)
            res = replay_and_verify(
                raw, cfg, expected_digest=args.expected_digest, as_of_timestamp=args.as_of
            )
            print(
                json.dumps(
                    {
                        "run_id": res["run_id"],
                        "logical_digest": res["logical_digest"],
                        "reproducible_match": res["reproducible_match"],
                    },
                    indent=2,
                )
            )
            return 0 if res["reproducible_match"] else 2

        if args.command == "evaluate":
            cfg = AgentConfig.from_file(args.config)
            eval_cfg = load_json_file(args.eval_config)
            suite = load_json_file(args.suite)
            result = evaluate_gold_suite(suite, cfg, eval_cfg)
            payload = json.dumps(result, indent=2)
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(payload + "\n", encoding="utf-8")
            else:
                print(payload)
            return 0 if result["all_targets_met"] else 2

    except EarningsCallAgentError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
