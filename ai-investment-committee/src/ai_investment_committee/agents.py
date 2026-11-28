"""Role-specific investment committee agents and optional LLM adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from .models import (
    AgentExecutionTrace,
    ChallengeRecord,
    Claim,
    CommitteeProposal,
    PortfolioReviewRecord,
    RiskVerdictRecord,
    ThesisRecord,
)
from .risk_engine import audit_claims, evaluate_risk_policy
from .tools import RoleToolSandbox


@dataclass(frozen=True)
class AdapterResponse:
    """Typed payload returned by an optional LLM or mock reasoning adapter."""

    summary: str
    claims: Tuple[Claim, ...]
    score: float
    tokens_used: int
    latency_ms: int
    cost_usd: float


class LLMAdapter(Protocol):
    """Protocol for pluggable reasoning adapters (offline deterministic mock by default)."""

    def generate_bull_thesis(
        self,
        *,
        proposal: CommitteeProposal,
        sanitized_briefs: Sequence[Dict[str, Any]],
        seed: int,
    ) -> AdapterResponse: ...

    def generate_bear_challenge(
        self,
        *,
        proposal: CommitteeProposal,
        sanitized_briefs: Sequence[Dict[str, Any]],
        thesis: ThesisRecord,
        seed: int,
    ) -> AdapterResponse: ...


class DeterministicMockAdapter:
    """Offline, seed-deterministic reasoning adapter grounded strictly in sanitized briefs."""

    def generate_bull_thesis(
        self,
        *,
        proposal: CommitteeProposal,
        sanitized_briefs: Sequence[Dict[str, Any]],
        seed: int,
    ) -> AdapterResponse:
        del seed  # Deterministic behavior; recorded in trace for reproducibility.
        ticker = proposal.candidate_position.ticker
        claims: List[Claim] = []
        idx = 1

        for brief in sanitized_briefs:
            if brief.get("stance_hint") != "bullish":
                continue
            for snip in brief.get("snippets", []):
                eid = snip["evidence_id"]
                text = snip["text"]
                if snip.get("injection_detected"):
                    claims.append(
                        Claim(
                            claim_id=f"BULL-{idx}",
                            author_role="bull",
                            statement=(
                                f"Untrusted snippet {eid} contained prompt-injection directives "
                                f"and was quarantined; remaining text for {ticker}: {text}"
                            ),
                            evidence_ids=(eid,),
                            is_uncertain=True,
                            uncertainty_reason="Source snippet contained untrusted prompt-injection directives and requires human verification.",
                            citation_status="UNCERTAIN",
                        )
                    )
                else:
                    claims.append(
                        Claim(
                            claim_id=f"BULL-{idx}",
                            author_role="bull",
                            statement=f"{ticker} bullish support: {text}",
                            evidence_ids=(eid,),
                            is_uncertain=False,
                            citation_status="VERIFIED",
                        )
                    )
                idx += 1

        if not claims:
            claims.append(
                Claim(
                    claim_id="BULL-1",
                    author_role="bull",
                    statement=f"No bullish research brief snippets were provided for {ticker}; upside case is unsubstantiated.",
                    evidence_ids=(),
                    is_uncertain=True,
                    uncertainty_reason="No bullish evidence snippets present in research briefs.",
                    citation_status="UNCERTAIN",
                )
            )

        verified_count = sum(1 for c in claims if not c.is_uncertain)
        conviction = round(min(0.9, 0.35 + 0.2 * verified_count), 2)
        summary = (
            f"Bull case for {proposal.candidate_position.side} {proposal.candidate_position.quantity} "
            f"{ticker} based on {len(claims)} evidence-grounded claim(s) (conviction {conviction:.2f})."
        )
        return AdapterResponse(
            summary=summary,
            claims=tuple(claims),
            score=conviction,
            tokens_used=220,
            latency_ms=45,
            cost_usd=0.0022,
        )

    def generate_bear_challenge(
        self,
        *,
        proposal: CommitteeProposal,
        sanitized_briefs: Sequence[Dict[str, Any]],
        thesis: ThesisRecord,
        seed: int,
    ) -> AdapterResponse:
        del seed
        ticker = proposal.candidate_position.ticker
        claims: List[Claim] = []
        idx = 1

        for brief in sanitized_briefs:
            if brief.get("stance_hint") != "bearish":
                continue
            for snip in brief.get("snippets", []):
                eid = snip["evidence_id"]
                text = snip["text"]
                claims.append(
                    Claim(
                        claim_id=f"BEAR-{idx}",
                        author_role="bear",
                        statement=f"{ticker} downside risk: {text}",
                        evidence_ids=(eid,),
                        is_uncertain=False,
                        citation_status="VERIFIED",
                    )
                )
                idx += 1

        if not claims:
            claims.append(
                Claim(
                    claim_id="BEAR-1",
                    author_role="bear",
                    statement=(
                        f"Limited bearish research coverage for {ticker}; absence of negative briefs "
                        "does not imply absence of execution or valuation risk."
                    ),
                    evidence_ids=(),
                    is_uncertain=True,
                    uncertainty_reason="No bearish brief snippets provided; adversarial coverage gap.",
                    citation_status="UNCERTAIN",
                )
            )

        bull_verified = sum(1 for c in thesis.claims if not c.is_uncertain)
        bear_verified = sum(1 for c in claims if not c.is_uncertain)
        if bear_verified > bull_verified:
            dissent_score = round(min(0.95, 0.65 + 0.1 * (bear_verified - bull_verified)), 2)
        elif bear_verified > 0:
            dissent_score = round(min(0.65, 0.40 + 0.1 * bear_verified), 2)
        else:
            dissent_score = 0.25

        summary = (
            f"Bear challenge against {ticker} thesis raised {len(claims)} risk/counter-claim(s) "
            f"(dissent score {dissent_score:.2f})."
        )
        return AdapterResponse(
            summary=summary,
            claims=tuple(claims),
            score=dissent_score,
            tokens_used=240,
            latency_ms=50,
            cost_usd=0.0024,
        )


class BullAgent:
    """Builds the evidence-backed bullish thesis using isolated research tools only."""

    def __init__(self, adapter: Optional[LLMAdapter] = None) -> None:
        self.adapter: LLMAdapter = adapter or DeterministicMockAdapter()

    def run(
        self,
        *,
        proposal: CommitteeProposal,
        sandbox: RoleToolSandbox,
        seed: int,
    ) -> Tuple[ThesisRecord, AgentExecutionTrace]:
        sandbox.invoke("get_candidate_position")
        briefs_res = sandbox.invoke("get_research_briefs", {"stance": "bullish"})
        resp = self.adapter.generate_bull_thesis(
            proposal=proposal,
            sanitized_briefs=briefs_res["briefs"],
            seed=seed,
        )
        sandbox.charge_reasoning_budget(
            tokens=resp.tokens_used,
            latency_ms=resp.latency_ms,
            cost_usd=resp.cost_usd,
        )
        trace = sandbox.build_trace()
        record = ThesisRecord(
            proposal_id=proposal.proposal_id,
            ticker=proposal.candidate_position.ticker,
            stance="bullish",
            conviction_score=resp.score,
            summary=resp.summary,
            claims=resp.claims,
            injection_flags=trace.injection_attempts_flagged,
        )
        return record, trace


class BearAgent:
    """Adversarially challenges the Bull thesis using isolated research & thesis inspection tools."""

    def __init__(self, adapter: Optional[LLMAdapter] = None) -> None:
        self.adapter: LLMAdapter = adapter or DeterministicMockAdapter()

    def run(
        self,
        *,
        proposal: CommitteeProposal,
        thesis: ThesisRecord,
        sandbox: RoleToolSandbox,
        seed: int,
    ) -> Tuple[ChallengeRecord, AgentExecutionTrace]:
        sandbox.invoke("get_candidate_position")
        sandbox.invoke("inspect_thesis_claims")
        briefs_res = sandbox.invoke("get_research_briefs", {"stance": "bearish"})
        resp = self.adapter.generate_bear_challenge(
            proposal=proposal,
            sanitized_briefs=briefs_res["briefs"],
            thesis=thesis,
            seed=seed,
        )
        sandbox.charge_reasoning_budget(
            tokens=resp.tokens_used,
            latency_ms=resp.latency_ms,
            cost_usd=resp.cost_usd,
        )
        trace = sandbox.build_trace()
        dissent_score = resp.score
        if dissent_score >= 0.70:
            dissent_level = "HIGH"
        elif dissent_score >= 0.40:
            dissent_level = "MODERATE"
        else:
            dissent_level = "LOW"

        challenged_ids = tuple(c.claim_id for c in thesis.claims)
        record = ChallengeRecord(
            proposal_id=proposal.proposal_id,
            ticker=proposal.candidate_position.ticker,
            dissent_level=dissent_level,
            dissent_score=dissent_score,
            challenged_claim_ids=challenged_ids,
            summary=resp.summary,
            claims=resp.claims,
            injection_flags=trace.injection_attempts_flagged,
        )
        return record, trace


class PortfolioAgent:
    """Evaluates portfolio fit, concentration, and sizing using portfolio tools only (no prose briefs)."""

    def run(
        self,
        *,
        proposal: CommitteeProposal,
        sandbox: RoleToolSandbox,
    ) -> Tuple[PortfolioReviewRecord, AgentExecutionTrace]:
        sandbox.invoke("get_candidate_position")
        sandbox.invoke("get_portfolio_state")
        exposure_res = sandbox.invoke("compute_pro_forma_exposure")
        metrics = exposure_res["pro_forma_metrics"]

        sandbox.charge_reasoning_budget(tokens=140, latency_ms=30, cost_usd=0.0014)
        trace = sandbox.build_trace()

        policy = proposal.risk_policy
        pos = proposal.candidate_position
        breaches = (
            metrics["pro_forma_ticker_weight_pct"] > policy.max_single_position_weight_pct
            or metrics["pro_forma_sector_weight_pct"] > policy.max_sector_weight_pct
            or metrics["pro_forma_cash_reserve_pct"] < policy.min_cash_reserve_pct
            or metrics["adv_participation_pct"] > policy.max_adv_participation_pct
        )
        if breaches:
            sizing_rec = "EXCEEDS_POLICY_LIMITS"
        elif metrics["pro_forma_ticker_weight_pct"] >= policy.max_single_position_weight_pct * 0.85:
            sizing_rec = "RESIZE_OR_MONITOR_NEAR_CAP"
        else:
            sizing_rec = "PROCEED_WITHIN_LIMITS"

        claim = Claim(
            claim_id="PORT-1",
            author_role="portfolio",
            statement=(
                f"Pro-forma {pos.ticker} weight is {metrics['pro_forma_ticker_weight_pct']:.2f}%, "
                f"{pos.sector} sector weight is {metrics['pro_forma_sector_weight_pct']:.2f}%, "
                f"and cash reserve is {metrics['pro_forma_cash_reserve_pct']:.2f}%."
            ),
            evidence_ids=(),
            is_uncertain=True,
            uncertainty_reason="Pro-forma portfolio projection derived from static snapshot and parametric volatility assumptions.",
            citation_status="UNCERTAIN",
        )
        summary = (
            f"Portfolio review for {pos.ticker}: {sizing_rec} "
            f"(pro-forma weight {metrics['pro_forma_ticker_weight_pct']:.2f}%, "
            f"estimated 1d 95% VaR {metrics['pro_forma_estimated_var_95_pct']:.4f}%)."
        )
        record = PortfolioReviewRecord(
            proposal_id=proposal.proposal_id,
            ticker=pos.ticker,
            sizing_recommendation=sizing_rec,
            pro_forma_metrics=metrics,
            summary=summary,
            claims=(claim,),
        )
        return record, trace


class IndependentRiskAgent:
    """Runs deterministic policy evaluation and citation verification completely isolated from persuasion."""

    def run(
        self,
        *,
        proposal: CommitteeProposal,
        all_claims: Sequence[Claim],
        sandbox: RoleToolSandbox,
    ) -> Tuple[RiskVerdictRecord, Tuple[Claim, ...], Dict[str, Any], AgentExecutionTrace]:
        sandbox.invoke("get_candidate_position")
        sandbox.invoke("get_portfolio_state")
        sandbox.invoke("get_risk_policy")
        sandbox.invoke("compute_pro_forma_exposure")
        sandbox.invoke("verify_evidence_citations")

        audited_claims, citation_audit = audit_claims(proposal, all_claims)
        verdict = evaluate_risk_policy(proposal, citation_audit)

        sandbox.charge_reasoning_budget(tokens=90, latency_ms=20, cost_usd=0.0009)
        trace = sandbox.build_trace()
        return verdict, audited_claims, citation_audit, trace
