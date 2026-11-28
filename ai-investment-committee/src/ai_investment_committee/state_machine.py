"""Pure domain deliberation orchestration and human-approval state transitions.

Contains zero database or filesystem I/O so domain state transitions are deterministic
and independently testable.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .agents import BearAgent, BullAgent, IndependentRiskAgent, LLMAdapter, PortfolioAgent
from .errors import (
    DuplicateApprovalError,
    InvalidStateTransitionError,
    ProposalHashMismatchError,
    RiskVetoBypassError,
)
from .hashing import compute_config_hash, compute_decision_id, compute_proposal_hash
from .models import (
    EXECUTION_CAPABILITY_NONE,
    SUPPORTED_SCHEMA_VERSION,
    AgentExecutionTrace,
    ChallengeRecord,
    Claim,
    CommitteeConfig,
    CommitteeProposal,
    DecisionRecord,
    DeliberationReplayTrace,
    HumanApprovalRecord,
    PortfolioReviewRecord,
    ThesisRecord,
)
from .tools import RoleToolSandbox


def _runtime_metadata() -> Dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }


def _rebind_audited_claims(
    thesis: ThesisRecord,
    challenge: ChallengeRecord,
    portfolio_review: PortfolioReviewRecord,
    audited_claims: Tuple[Claim, ...],
) -> Tuple[ThesisRecord, ChallengeRecord, PortfolioReviewRecord]:
    by_id = {c.claim_id: c for c in audited_claims}
    updated_thesis = replace(thesis, claims=tuple(by_id[c.claim_id] for c in thesis.claims))
    updated_challenge = replace(challenge, claims=tuple(by_id[c.claim_id] for c in challenge.claims))
    updated_portfolio = replace(
        portfolio_review, claims=tuple(by_id[c.claim_id] for c in portfolio_review.claims)
    )
    return updated_thesis, updated_challenge, updated_portfolio


def run_deliberation(
    *,
    proposal: CommitteeProposal,
    config: CommitteeConfig,
    adapter: Optional[LLMAdapter] = None,
    simulated_role_delay_ms: Optional[Dict[str, int]] = None,
    created_at_override: Optional[str] = None,
) -> DeliberationReplayTrace:
    """Execute one complete, deterministic committee deliberation without external I/O."""
    delays = simulated_role_delay_ms or {}
    proposal_hash = compute_proposal_hash(proposal.model_dump())
    config_hash = compute_config_hash(config.model_dump())
    decision_id = compute_decision_id(proposal_hash, config_hash, config.seed)

    bull_sandbox = RoleToolSandbox(
        role="bull",
        proposal=proposal,
        budget=config.agent_budgets["bull"],
        extra_latency_ms=delays.get("bull", 0),
    )
    thesis, bull_trace = BullAgent(adapter=adapter).run(
        proposal=proposal,
        sandbox=bull_sandbox,
        seed=config.seed,
    )

    bear_sandbox = RoleToolSandbox(
        role="bear",
        proposal=proposal,
        budget=config.agent_budgets["bear"],
        thesis=thesis,
        extra_latency_ms=delays.get("bear", 0),
    )
    challenge, bear_trace = BearAgent(adapter=adapter).run(
        proposal=proposal,
        thesis=thesis,
        sandbox=bear_sandbox,
        seed=config.seed,
    )

    portfolio_sandbox = RoleToolSandbox(
        role="portfolio",
        proposal=proposal,
        budget=config.agent_budgets["portfolio"],
        extra_latency_ms=delays.get("portfolio", 0),
    )
    portfolio_review, portfolio_trace = PortfolioAgent().run(
        proposal=proposal,
        sandbox=portfolio_sandbox,
    )

    combined_claims: List[Claim] = list(thesis.claims) + list(challenge.claims) + list(portfolio_review.claims)
    risk_sandbox = RoleToolSandbox(
        role="risk",
        proposal=proposal,
        budget=config.agent_budgets["risk"],
        claims_for_audit=combined_claims,
        extra_latency_ms=delays.get("risk", 0),
    )
    risk_verdict, audited_claims, citation_audit, risk_trace = IndependentRiskAgent().run(
        proposal=proposal,
        all_claims=combined_claims,
        sandbox=risk_sandbox,
    )

    audited_thesis, audited_challenge, audited_portfolio = _rebind_audited_claims(
        thesis, challenge, portfolio_review, audited_claims
    )

    notes: List[str] = []
    if citation_audit["fabricated_citations"] > 0:
        notes.append(
            f"Citation audit detected {citation_audit['fabricated_citations']} fabricated citation(s); affected claims marked uncertain."
        )
    injection_count = len(bull_trace.injection_attempts_flagged) + len(bear_trace.injection_attempts_flagged)
    if injection_count > 0:
        notes.append(
            f"Quarantined {injection_count} prompt-injection directive(s) in untrusted research briefs."
        )

    if risk_verdict.verdict == "VETO":
        status = "VETOED"
        notes.append("Deterministic risk veto is final and cannot be bypassed.")
    else:
        status = "AWAITING_HUMAN_APPROVAL"
        notes.append(
            "Agent consensus is not independent evidence; human approval bound to proposal_hash is required."
        )

    decision = DecisionRecord(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        decision_id=decision_id,
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal_hash,
        config_id=config.config_id,
        config_hash=config_hash,
        seed=config.seed,
        status=status,
        execution_capability=EXECUTION_CAPABILITY_NONE,
        thesis=audited_thesis,
        challenge=audited_challenge,
        portfolio_review=audited_portfolio,
        risk_verdict=risk_verdict,
        human_approval=None,
        notes=tuple(notes),
    )

    agent_traces: Tuple[AgentExecutionTrace, ...] = (
        bull_trace,
        bear_trace,
        portfolio_trace,
        risk_trace,
    )
    created_at = created_at_override or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return DeliberationReplayTrace(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        decision_id=decision_id,
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal_hash,
        config_hash=config_hash,
        seed=config.seed,
        created_at=created_at,
        decision=decision,
        agent_traces=agent_traces,
        total_tool_calls=sum(t.tool_calls_used for t in agent_traces),
        total_tokens=sum(t.tokens_used for t in agent_traces),
        total_latency_ms=sum(t.latency_ms for t in agent_traces),
        total_cost_usd=round(sum(t.cost_usd for t in agent_traces), 6),
        runtime_metadata=_runtime_metadata(),
    )


def apply_human_approval(
    *,
    decision: DecisionRecord,
    approval: HumanApprovalRecord,
    seen_approval_ids: Iterable[str] = (),
) -> DecisionRecord:
    """Enforce non-overridable risk veto, hash binding, and duplicate-approval protection."""
    seen = set(seen_approval_ids)
    if approval.approval_id in seen:
        raise DuplicateApprovalError(
            f"Approval ID '{approval.approval_id}' has already been processed.",
            details={"approval_id": approval.approval_id, "decision_id": decision.decision_id},
        )

    if decision.human_approval is not None or decision.status in {
        "APPROVED_FOR_PAPER_ONLY",
        "REJECTED_BY_HUMAN",
    }:
        raise DuplicateApprovalError(
            f"Decision '{decision.decision_id}' already has a finalized human decision ({decision.status}).",
            details={
                "decision_id": decision.decision_id,
                "existing_status": decision.status,
                "existing_approval_id": decision.human_approval.approval_id
                if decision.human_approval
                else None,
            },
        )

    if decision.risk_verdict.verdict == "VETO" or decision.status == "VETOED":
        raise RiskVetoBypassError(
            f"Cannot apply human approval to risk-vetoed decision '{decision.decision_id}'. Violated rules: {list(decision.risk_verdict.violated_rules)}",
            details={
                "decision_id": decision.decision_id,
                "violated_rules": list(decision.risk_verdict.violated_rules),
            },
        )

    if decision.status != "AWAITING_HUMAN_APPROVAL":
        raise InvalidStateTransitionError(
            f"Decision '{decision.decision_id}' is in status '{decision.status}', expected 'AWAITING_HUMAN_APPROVAL'.",
            details={"decision_id": decision.decision_id, "status": decision.status},
        )

    if approval.proposal_id != decision.proposal_id:
        raise ProposalHashMismatchError(
            f"Approval proposal_id '{approval.proposal_id}' does not match decision proposal_id '{decision.proposal_id}'.",
            details={
                "expected_proposal_id": decision.proposal_id,
                "provided_proposal_id": approval.proposal_id,
            },
        )

    if approval.proposal_hash != decision.proposal_hash:
        raise ProposalHashMismatchError(
            f"Approval proposal_hash '{approval.proposal_hash}' does not match canonical proposal_hash '{decision.proposal_hash}'.",
            details={
                "expected_proposal_hash": decision.proposal_hash,
                "provided_proposal_hash": approval.proposal_hash,
            },
        )

    new_status = (
        "APPROVED_FOR_PAPER_ONLY" if approval.decision == "APPROVE_PAPER" else "REJECTED_BY_HUMAN"
    )
    updated_notes = decision.notes + (
        f"Human reviewer '{approval.reviewer_id}' recorded '{approval.decision}' (approval_id={approval.approval_id}).",
    )
    return replace(
        decision,
        status=new_status,
        human_approval=approval,
        notes=updated_notes,
    )
