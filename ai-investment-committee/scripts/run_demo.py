#!/usr/bin/env python3
"""Reproducible end-to-end demo covering all committee governance scenarios."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_investment_committee.agents import AdapterResponse, DeterministicMockAdapter
from ai_investment_committee.errors import (
    AgentTimeoutError,
    DuplicateApprovalError,
    RiskVetoBypassError,
)
from ai_investment_committee.models import Claim, CommitteeProposal, HumanApprovalRecord
from ai_investment_committee.replay import compare_to_baseline, evaluate_deliberation
from ai_investment_committee.service import InvestmentCommitteeService, load_json_file

CONFIG_PATH = PROJECT_ROOT / "config" / "committee_default.json"
FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
REPORTS_DIR = PROJECT_ROOT / "reports"
DB_PATH = REPORTS_DIR / "demo_deliberations.sqlite3"


class DemoFabricatingAdapter(DeterministicMockAdapter):
    """Demo adapter that injects a fabricated evidence citation to demonstrate citation audit + veto."""

    def generate_bull_thesis(
        self,
        *,
        proposal: CommitteeProposal,
        sanitized_briefs: Sequence[Dict[str, Any]],
        seed: int,
    ) -> AdapterResponse:
        base = super().generate_bull_thesis(
            proposal=proposal, sanitized_briefs=sanitized_briefs, seed=seed
        )
        fabricated = Claim(
            claim_id="BULL-FAB-DEMO",
            author_role="bull",
            statement="Fabricated citation attempt referencing EV-NONEXISTENT-404.",
            evidence_ids=("EV-NONEXISTENT-404",),
            is_uncertain=False,
            citation_status="VERIFIED",
        )
        return AdapterResponse(
            summary=base.summary,
            claims=base.claims + (fabricated,),
            score=base.score,
            tokens_used=base.tokens_used,
            latency_ms=base.latency_ms,
            cost_usd=base.cost_usd,
        )


def run_demo() -> Dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    service = InvestmentCommitteeService.from_config_path(
        config_path=CONFIG_PATH,
        db_path=DB_PATH,
    )

    # 1. Reference proposal -> PASS -> Hash-bound human approval -> Replay -> Baseline comparison
    ref_raw = load_json_file(FIXTURES_DIR / "valid_reference_proposal.json", label="reference proposal")
    oracle = load_json_file(FIXTURES_DIR / "reference_expected_output.json", label="reference oracle")
    ref_trace = service.deliberate(ref_raw, created_at_override="2026-11-28T09:00:00Z")
    baseline_comparison = compare_to_baseline(trace=ref_trace, oracle=oracle)

    approval = HumanApprovalRecord(
        approval_id="DEMO-APP-001",
        proposal_id=ref_trace.proposal_id,
        proposal_hash=ref_trace.proposal_hash,
        reviewer_id="demo-pm-01",
        decision="APPROVE_PAPER",
        rationale="Verified bull/bear dissent, portfolio exposure, and deterministic PASS verdict.",
        approved_at="2026-11-28T09:01:00Z",
    )
    approved_trace = service.submit_human_approval(
        decision_id=ref_trace.decision_id,
        approval_input=approval,
    )
    ref_replay = service.replay(ref_trace.decision_id)

    # Duplicate approval regression check
    duplicate_approval_blocked = False
    try:
        service.submit_human_approval(decision_id=ref_trace.decision_id, approval_input=approval)
    except DuplicateApprovalError:
        duplicate_approval_blocked = True

    # 2. Agent disagreement & fabricated evidence scenario
    disagree_raw = load_json_file(
        FIXTURES_DIR / "disagreement_fabricated_evidence.json",
        label="disagreement fixture",
    )
    disagree_trace = service.deliberate(disagree_raw, created_at_override="2026-11-28T09:05:00Z")
    disagree_eval = evaluate_deliberation(disagree_trace).model_dump()

    fab_service = InvestmentCommitteeService.from_config_path(
        config_path=CONFIG_PATH,
        db_path=REPORTS_DIR / "demo_fabricated.sqlite3",
        adapter=DemoFabricatingAdapter(),
    )
    fab_trace = fab_service.deliberate(disagree_raw, created_at_override="2026-11-28T09:06:00Z")
    fab_eval = evaluate_deliberation(fab_trace).model_dump()

    # 3. Prompt injection + deterministic risk veto + veto bypass attempt
    inject_raw = load_json_file(
        FIXTURES_DIR / "prompt_injection_risk_veto.json",
        label="prompt injection fixture",
    )
    inject_trace = service.deliberate(inject_raw, created_at_override="2026-11-28T09:10:00Z")
    inject_eval = evaluate_deliberation(inject_trace).model_dump()
    veto_bypass_blocked = False
    try:
        service.submit_human_approval(
            decision_id=inject_trace.decision_id,
            approval_input=HumanApprovalRecord(
                approval_id="DEMO-BYPASS-ATTEMPT",
                proposal_id=inject_trace.proposal_id,
                proposal_hash=inject_trace.proposal_hash,
                reviewer_id="demo-pm-01",
                decision="APPROVE_PAPER",
                rationale="Attempt to bypass risk veto.",
                approved_at="2026-11-28T09:11:00Z",
            ),
        )
    except RiskVetoBypassError:
        veto_bypass_blocked = True

    # 4. Agent timeout boundary check
    timeout_error_captured: Dict[str, Any] = {}
    try:
        service.deliberate(ref_raw, simulated_role_delay_ms={"bear": 2500})
    except AgentTimeoutError as exc:
        timeout_error_captured = exc.to_dict()

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "config_id": service.config.config_id,
            "seed": service.config.seed,
            "adapter_mode": service.config.adapter_mode,
            "allow_live_execution": service.config.allow_live_execution,
        },
        "scenarios": {
            "reference_proposal": {
                "decision_id": ref_trace.decision_id,
                "proposal_hash": ref_trace.proposal_hash,
                "verdict": ref_trace.decision.risk_verdict.verdict,
                "status_before_human": ref_trace.decision.status,
                "status_after_human": approved_trace.decision.status,
                "execution_capability": approved_trace.decision.execution_capability,
                "replay_exact_match": ref_replay["exact_match"],
                "evaluation": ref_replay["evaluation"],
                "duplicate_approval_blocked": duplicate_approval_blocked,
            },
            "agent_disagreement": {
                "decision_id": disagree_trace.decision_id,
                "dissent_level": disagree_trace.decision.challenge.dissent_level,
                "dissent_score": disagree_trace.decision.challenge.dissent_score,
                "verdict": disagree_trace.decision.risk_verdict.verdict,
                "evaluation": disagree_eval,
            },
            "fabricated_evidence": {
                "decision_id": fab_trace.decision_id,
                "verdict": fab_trace.decision.risk_verdict.verdict,
                "violated_rules": list(fab_trace.decision.risk_verdict.violated_rules),
                "status": fab_trace.decision.status,
                "evaluation": fab_eval,
            },
            "prompt_injection_and_risk_veto": {
                "decision_id": inject_trace.decision_id,
                "verdict": inject_trace.decision.risk_verdict.verdict,
                "violated_rules": list(inject_trace.decision.risk_verdict.violated_rules),
                "status": inject_trace.decision.status,
                "veto_bypass_blocked": veto_bypass_blocked,
                "evaluation": inject_eval,
            },
            "agent_timeout_boundary": {
                "timeout_captured": bool(timeout_error_captured),
                "error": timeout_error_captured,
            },
        },
        "service_counters": dict(service.counters),
    }

    (REPORTS_DIR / "demo_run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (REPORTS_DIR / "baseline_comparison.json").write_text(
        json.dumps(baseline_comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    result = run_demo()
    print(json.dumps(result, indent=2, sort_keys=True))
