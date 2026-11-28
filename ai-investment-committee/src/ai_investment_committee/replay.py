"""Deliberation replay, evaluation metrics (dissent, unsupported claims, cost), and baseline comparison."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .agents import LLMAdapter
from .models import (
    CommitteeConfig,
    CommitteeProposal,
    DeliberationReplayTrace,
    EvaluationMetrics,
)
from .state_machine import run_deliberation


def evaluate_deliberation(trace: DeliberationReplayTrace) -> EvaluationMetrics:
    """Compute structured governance, citation-integrity, dissent, and cost metrics from a replay trace."""
    decision = trace.decision
    all_claims = (
        list(decision.thesis.claims)
        + list(decision.challenge.claims)
        + list(decision.portfolio_review.claims)
    )

    verified_cited = 0
    uncertain = 0
    unsupported = 0
    fabricated = 0

    for claim in all_claims:
        fabricated += len(claim.fabricated_evidence_ids)
        if claim.citation_status == "VERIFIED" and claim.evidence_ids and not claim.is_uncertain:
            verified_cited += 1
        elif claim.is_uncertain and claim.uncertainty_reason:
            uncertain += 1
        else:
            unsupported += 1

    all_compliant = (unsupported == 0) and all(
        (bool(c.evidence_ids) and c.citation_status == "VERIFIED") or c.is_uncertain
        for c in all_claims
    )

    injection_attempts = sum(len(t.injection_attempts_flagged) for t in trace.agent_traces)

    budget_utilization: Dict[str, float] = {}
    for agent_trace in trace.agent_traces:
        token_pct = (agent_trace.tokens_used / agent_trace.budget.max_tokens) * 100.0
        cost_pct = (agent_trace.cost_usd / agent_trace.budget.max_cost_usd) * 100.0
        call_pct = (agent_trace.tool_calls_used / agent_trace.budget.max_tool_calls) * 100.0
        budget_utilization[agent_trace.role] = round(max(token_pct, cost_pct, call_pct), 2)

    return EvaluationMetrics(
        decision_id=trace.decision_id,
        proposal_id=trace.proposal_id,
        dissent_present=decision.challenge.dissent_score > 0.0,
        dissent_score=decision.challenge.dissent_score,
        total_claims=len(all_claims),
        verified_cited_claims=verified_cited,
        uncertain_claims=uncertain,
        unsupported_claims=unsupported,
        fabricated_citations=fabricated,
        all_claims_cited_or_uncertain=all_compliant,
        prompt_injection_attempts_detected=injection_attempts,
        total_tool_calls=trace.total_tool_calls,
        total_tokens=trace.total_tokens,
        total_latency_ms=trace.total_latency_ms,
        total_cost_usd=trace.total_cost_usd,
        budget_utilization_pct=budget_utilization,
        verdict=decision.risk_verdict.verdict,
        status=decision.status,
    )


def replay_deliberation(
    *,
    recorded_trace: DeliberationReplayTrace,
    proposal_dict: Dict[str, Any],
    config_dict: Dict[str, Any],
    adapter: Optional[LLMAdapter] = None,
) -> Dict[str, Any]:
    """Deterministically re-execute a persisted deliberation and compare logical outputs & budget."""
    proposal = CommitteeProposal.model_validate(proposal_dict)
    config = CommitteeConfig.model_validate(config_dict)
    replayed = run_deliberation(
        proposal=proposal,
        config=config,
        adapter=adapter,
        created_at_override=recorded_trace.created_at,
    )

    mismatches: List[str] = []
    if replayed.decision_id != recorded_trace.decision_id:
        mismatches.append("decision_id")
    if replayed.proposal_hash != recorded_trace.proposal_hash:
        mismatches.append("proposal_hash")
    if replayed.config_hash != recorded_trace.config_hash:
        mismatches.append("config_hash")
    if replayed.decision.risk_verdict.model_dump() != recorded_trace.decision.risk_verdict.model_dump():
        mismatches.append("risk_verdict")
    if replayed.total_tool_calls != recorded_trace.total_tool_calls:
        mismatches.append("total_tool_calls")
    if replayed.total_tokens != recorded_trace.total_tokens:
        mismatches.append("total_tokens")
    if abs(replayed.total_cost_usd - recorded_trace.total_cost_usd) > 1e-6:
        mismatches.append("total_cost_usd")

    return {
        "decision_id": recorded_trace.decision_id,
        "exact_match": len(mismatches) == 0,
        "mismatches": mismatches,
        "recorded_verdict": recorded_trace.decision.risk_verdict.verdict,
        "replayed_verdict": replayed.decision.risk_verdict.verdict,
        "recorded_status": recorded_trace.decision.status,
        "replayed_pre_approval_status": replayed.decision.status,
        "recorded_budget": {
            "tool_calls": recorded_trace.total_tool_calls,
            "tokens": recorded_trace.total_tokens,
            "latency_ms": recorded_trace.total_latency_ms,
            "cost_usd": recorded_trace.total_cost_usd,
        },
        "replayed_budget": {
            "tool_calls": replayed.total_tool_calls,
            "tokens": replayed.total_tokens,
            "latency_ms": replayed.total_latency_ms,
            "cost_usd": replayed.total_cost_usd,
        },
        "evaluation": evaluate_deliberation(recorded_trace).model_dump(),
    }


def compare_to_baseline(
    *,
    trace: DeliberationReplayTrace,
    oracle: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare actual deliberation metrics and verdict against an independent reference oracle."""
    actual_metrics = trace.decision.risk_verdict.metrics
    expected_metrics = oracle["expected_metrics"]
    tolerances = oracle["tolerances"]

    metric_diffs: Dict[str, Dict[str, Any]] = {}
    all_within_tolerance = True
    for key, expected_val in expected_metrics.items():
        actual_val = actual_metrics.get(key)
        tol = tolerances["usd_abs"] if key.endswith("_usd") else tolerances["percentage_abs"]
        diff = abs(float(actual_val) - float(expected_val)) if actual_val is not None else float("inf")
        ok = diff <= tol
        if not ok:
            all_within_tolerance = False
        metric_diffs[key] = {
            "expected": expected_val,
            "actual": actual_val,
            "abs_diff": round(diff, 6),
            "tolerance": tol,
            "within_tolerance": ok,
        }

    eval_metrics = evaluate_deliberation(trace)
    verdict_ok = trace.decision.risk_verdict.verdict == oracle["expected_verdict"]
    violated_ok = list(trace.decision.risk_verdict.violated_rules) == oracle["expected_violated_rules"]
    status_ok = trace.decision.status in {
        oracle["expected_decision_status_before_human"],
        oracle["expected_decision_status_after_human_approve"],
    }
    invariants_ok = (
        trace.decision.execution_capability == oracle["expected_invariants"]["execution_capability"]
        and eval_metrics.all_claims_cited_or_uncertain
        == oracle["expected_invariants"]["all_claims_cited_or_uncertain"]
        and eval_metrics.fabricated_citations == oracle["expected_invariants"]["fabricated_citations"]
        and (eval_metrics.prompt_injection_attempts_detected > 0)
        == oracle["expected_invariants"]["prompt_injection_detected"]
    )

    return {
        "proposal_id": trace.proposal_id,
        "decision_id": trace.decision_id,
        "passed": all_within_tolerance and verdict_ok and violated_ok and status_ok and invariants_ok,
        "verdict_match": verdict_ok,
        "violated_rules_match": violated_ok,
        "status_match": status_ok,
        "invariants_match": invariants_ok,
        "all_metrics_within_tolerance": all_within_tolerance,
        "metric_comparison": metric_diffs,
    }
