#!/usr/bin/env python3
"""Reproducible evaluation runner that generates versioned JSON/Markdown artifacts in reports/."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_incident_agent.agent import TradingIncidentAgent, render_report_markdown
from trading_incident_agent.config import load_config, load_incident_bundle
from trading_incident_agent.evaluator import evaluate_against_oracle
from trading_incident_agent.models import OperatorApproval
from trading_incident_agent.remediation import SimulatedTradingEnvironment


def main() -> int:
    fixtures_dir = PROJECT_ROOT / "data" / "fixtures"
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(PROJECT_ROOT / "config" / "default.json")
    agent = TradingIncidentAgent(config=config)

    # 1. Run oracle evaluation across all synthetic scenarios
    eval_summary = evaluate_against_oracle(fixtures_dir, config=config)
    (reports_dir / "evaluation_summary.json").write_text(
        json.dumps(eval_summary, indent=2) + "\n", encoding="utf-8"
    )

    # 2. Generate individual raw JSON + Markdown reports for each reference scenario
    fixture_files = [
        "inc_ref_001_gateway_pool.json",
        "inc_missing_spans_002.json",
        "inc_prompt_injection_003.json",
        "inc_ambiguous_004.json",
    ]
    ref_report = None
    for fname in fixture_files:
        bundle = load_incident_bundle(fixtures_dir / fname)
        report = agent.investigate(bundle)
        stem = bundle.incident_id.lower().replace("-", "_")
        (reports_dir / f"{stem}_report.json").write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (reports_dir / f"{stem}_report.md").write_text(
            render_report_markdown(report), encoding="utf-8"
        )
        if bundle.incident_id == "INC-REF-001":
            ref_report = report

    # 3. Generate approved simulated remediation & recovery verification receipt for reference scenario
    assert ref_report is not None and ref_report.proposed_remediations
    prop = ref_report.proposed_remediations[0]
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    approval = OperatorApproval(
        approval_id="APR-REF-001-DEMO",
        incident_id=ref_report.incident_id,
        remediation_id=prop.remediation_id,
        plan_digest=prop.plan_digest,
        approver_id="sre_lead_sim",
        approver_role="oncall_sre",
        approved_at_utc=now,
        expires_at_utc=now + timedelta(minutes=15),
        rationale="Reviewed cited gateway pool spans, OMS timeouts, and alert; approved simulated drain.",
    )
    sim_env = SimulatedTradingEnvironment(seed=config.seed)
    receipt = agent.execute_remediation(
        report=ref_report,
        proposal=prop,
        approval=approval,
        environment=sim_env,
        now_utc=now,
    )
    (reports_dir / "remediation_demo_receipt.json").write_text(
        receipt.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(eval_summary["aggregate_metrics"], indent=2))
    print(f"All scenarios passed: {eval_summary['all_scenarios_passed']}")
    return 0 if eval_summary["all_scenarios_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
