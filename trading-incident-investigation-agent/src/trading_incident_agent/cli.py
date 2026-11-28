"""Command-line interface for running investigations, simulated remediation demos, and evaluations."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_incident_agent.agent import TradingIncidentAgent, render_report_markdown
from trading_incident_agent.config import load_config, load_incident_bundle
from trading_incident_agent.errors import IncidentAgentError
from trading_incident_agent.evaluator import evaluate_against_oracle
from trading_incident_agent.models import AgentConfig, OperatorApproval
from trading_incident_agent.remediation import SimulatedTradingEnvironment


def _resolve_config(config_path: str | None) -> AgentConfig:
    if config_path:
        return load_config(config_path)
    return AgentConfig()


def cmd_investigate(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    bundle = load_incident_bundle(args.fixture)
    agent = TradingIncidentAgent(config=config)
    report = agent.investigate(bundle)

    if args.output_json:
        out_json = Path(args.output_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    if args.output_md:
        out_md = Path(args.output_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_report_markdown(report), encoding="utf-8")

    if not args.quiet:
        print(render_report_markdown(report))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    summary = evaluate_against_oracle(args.fixtures_dir, config=config)
    rendered = json.dumps(summary, indent=2)
    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")
    if not args.quiet:
        print(rendered)
    return 0 if summary["all_scenarios_passed"] else 1


def cmd_demo(args: argparse.Namespace) -> int:
    config = _resolve_config(args.config)
    bundle = load_incident_bundle(args.fixture)
    agent = TradingIncidentAgent(config=config)

    report = agent.investigate(bundle)
    print(render_report_markdown(report))

    if report.proposed_remediations and args.approve_demo:
        proposal = report.proposed_remediations[0]
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        approval = OperatorApproval(
            approval_id=f"APR-DEMO-{report.incident_id}",
            incident_id=report.incident_id,
            remediation_id=proposal.remediation_id,
            plan_digest=proposal.plan_digest,
            approver_id="demo_sre_operator",
            approver_role="oncall_sre",
            approved_at_utc=now,
            expires_at_utc=now + timedelta(minutes=15),
            rationale="Demo operator explicitly approved bounded simulated remediation.",
            acknowledge_ambiguity=args.acknowledge_ambiguity,
        )
        env = SimulatedTradingEnvironment(seed=config.seed)
        receipt = agent.execute_remediation(
            report=report,
            proposal=proposal,
            approval=approval,
            environment=env,
            now_utc=now,
        )
        print("## Simulated Remediation Receipt (Explicitly Approved)\n")
        print(receipt.model_dump_json(indent=2))
    elif report.proposed_remediations:
        print(
            "Read-only mode active: simulated remediation was NOT executed. "
            "Pass --approve-demo to simulate explicit operator approval and recovery verification."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-incident-agent",
        description="Trading Incident Investigation Agent (offline synthetic/paper prototype).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inv = sub.add_parser("investigate", help="Run read-only investigation on an incident fixture.")
    p_inv.add_argument("--fixture", required=True, help="Path to IncidentBundle JSON fixture.")
    p_inv.add_argument("--config", default=None, help="Path to AgentConfig JSON file.")
    p_inv.add_argument("--output-json", default=None, help="Optional path to write JSON report.")
    p_inv.add_argument("--output-md", default=None, help="Optional path to write Markdown report.")
    p_inv.add_argument("--quiet", action="store_true", help="Suppress stdout markdown output.")
    p_inv.set_defaults(func=cmd_investigate)

    p_eval = sub.add_parser("evaluate", help="Evaluate all fixtures against reference_oracle.json.")
    p_eval.add_argument("--fixtures-dir", required=True, help="Directory containing fixtures and reference_oracle.json.")
    p_eval.add_argument("--config", default=None, help="Path to AgentConfig JSON file.")
    p_eval.add_argument("--output-json", default=None, help="Optional path to write evaluation JSON.")
    p_eval.add_argument("--quiet", action="store_true", help="Suppress stdout output.")
    p_eval.set_defaults(func=cmd_evaluate)

    p_demo = sub.add_parser("demo", help="Run end-to-end demo (read-only by default; optional simulated approval).")
    p_demo.add_argument("--fixture", required=True, help="Path to IncidentBundle JSON fixture.")
    p_demo.add_argument("--config", default=None, help="Path to AgentConfig JSON file.")
    p_demo.add_argument("--approve-demo", action="store_true", help="Simulate explicit operator approval and recovery verification.")
    p_demo.add_argument("--acknowledge-ambiguity", action="store_true", help="Explicitly acknowledge ambiguous verdict if applicable.")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except IncidentAgentError as exc:
        print(f"ERROR [{exc.error_code}]: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
