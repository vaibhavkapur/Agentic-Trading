"""Pure deterministic risk policy engine and citation auditor.

Completely isolated from I/O, LLM outputs, and untrusted research prose.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

from .models import (
    Claim,
    CommitteeProposal,
    RiskCheckResult,
    RiskVerdictRecord,
)

Z_SCORE_95 = 1.6448536
TRADING_DAYS_PER_YEAR = 252.0


def compute_pro_forma_metrics(proposal: CommitteeProposal) -> Dict[str, float]:
    """Deterministically calculate post-trade portfolio exposures and risk metrics."""
    pos = proposal.candidate_position
    pf = proposal.portfolio_state
    nav = pf.nav_usd

    trade_notional = round(pos.quantity * pos.limit_price_usd, 4)
    signed_trade = trade_notional if pos.side == "BUY" else -trade_notional

    current_ticker_val = 0.0
    current_sector_val = 0.0
    current_gross = 0.0
    for holding in pf.holdings:
        current_gross += abs(holding.market_value_usd)
        if holding.ticker == pos.ticker:
            current_ticker_val += holding.market_value_usd
        if holding.sector == pos.sector:
            current_sector_val += holding.market_value_usd

    pro_forma_ticker_val = round(current_ticker_val + signed_trade, 4)
    pro_forma_sector_val = round((current_sector_val - current_ticker_val) + pro_forma_ticker_val, 4)
    pro_forma_gross = round((current_gross - abs(current_ticker_val)) + abs(pro_forma_ticker_val), 4)
    pro_forma_cash = round(pf.cash_usd - signed_trade, 4)

    pro_forma_ticker_weight_pct = round((abs(pro_forma_ticker_val) / nav) * 100.0, 4)
    pro_forma_sector_weight_pct = round((abs(pro_forma_sector_val) / nav) * 100.0, 4)
    pro_forma_gross_exposure_pct = round((pro_forma_gross / nav) * 100.0, 4)
    pro_forma_cash_reserve_pct = round((pro_forma_cash / nav) * 100.0, 4)
    adv_participation_pct = round((pos.quantity / pos.average_daily_volume_shares) * 100.0, 4)

    standalone_var_delta = (
        (trade_notional / nav)
        * (pos.estimated_volatility_annual_pct / math.sqrt(TRADING_DAYS_PER_YEAR))
        * Z_SCORE_95
    )
    incremental_var_95_pct = round(
        standalone_var_delta if pos.side == "BUY" else -standalone_var_delta,
        4,
    )
    pro_forma_estimated_var_95_pct = round(
        max(0.0, pf.current_estimated_var_95_pct + incremental_var_95_pct),
        4,
    )

    return {
        "trade_notional_usd": trade_notional,
        "pro_forma_ticker_value_usd": pro_forma_ticker_val,
        "pro_forma_ticker_weight_pct": pro_forma_ticker_weight_pct,
        "pro_forma_sector_value_usd": pro_forma_sector_val,
        "pro_forma_sector_weight_pct": pro_forma_sector_weight_pct,
        "pro_forma_gross_exposure_usd": pro_forma_gross,
        "pro_forma_gross_exposure_pct": pro_forma_gross_exposure_pct,
        "pro_forma_cash_usd": pro_forma_cash,
        "pro_forma_cash_reserve_pct": pro_forma_cash_reserve_pct,
        "adv_participation_pct": adv_participation_pct,
        "incremental_var_95_pct": incremental_var_95_pct,
        "pro_forma_estimated_var_95_pct": pro_forma_estimated_var_95_pct,
    }


def audit_claims(
    proposal: CommitteeProposal,
    claims: Sequence[Claim],
) -> Tuple[Tuple[Claim, ...], Dict[str, Any]]:
    """Deterministically verify every claim citation against proposal research briefs.

    Any fabricated (non-existent) evidence ID is stripped from verified evidence_ids,
    recorded in `fabricated_evidence_ids`, and forces the claim to `citation_status='FABRICATED'`
    and `is_uncertain=True` so no unverified assertion can silently pass as cited fact.
    """
    valid_ids = set(proposal.evidence_index().keys())
    audited: List[Claim] = []

    verified_claims = 0
    uncertain_claims = 0
    fabricated_citation_count = 0

    for claim in claims:
        good_ids = tuple(eid for eid in claim.evidence_ids if eid in valid_ids)
        bad_ids = tuple(eid for eid in claim.evidence_ids if eid not in valid_ids)

        if bad_ids:
            fabricated_citation_count += len(bad_ids)
            uncertain_claims += 1
            reason = (
                f"Fabricated or unverified evidence citation(s): {', '.join(bad_ids)}"
            )
            audited.append(
                Claim(
                    claim_id=claim.claim_id,
                    author_role=claim.author_role,
                    statement=claim.statement,
                    evidence_ids=good_ids,
                    is_uncertain=True,
                    uncertainty_reason=reason,
                    citation_status="FABRICATED",
                    fabricated_evidence_ids=bad_ids,
                )
            )
        elif good_ids and not claim.is_uncertain:
            verified_claims += 1
            audited.append(
                Claim(
                    claim_id=claim.claim_id,
                    author_role=claim.author_role,
                    statement=claim.statement,
                    evidence_ids=good_ids,
                    is_uncertain=False,
                    uncertainty_reason=None,
                    citation_status="VERIFIED",
                    fabricated_evidence_ids=(),
                )
            )
        else:
            uncertain_claims += 1
            audited.append(
                Claim(
                    claim_id=claim.claim_id,
                    author_role=claim.author_role,
                    statement=claim.statement,
                    evidence_ids=good_ids,
                    is_uncertain=True,
                    uncertainty_reason=claim.uncertainty_reason
                    or "Marked uncertain without direct research brief citation",
                    citation_status="UNCERTAIN",
                    fabricated_evidence_ids=(),
                )
            )

    total_claims = len(audited)
    verified_ratio = round(verified_claims / total_claims, 4) if total_claims > 0 else 0.0
    summary = {
        "total_claims": total_claims,
        "verified_claims": verified_claims,
        "uncertain_claims": uncertain_claims,
        "fabricated_citations": fabricated_citation_count,
        "verified_citation_ratio": verified_ratio,
    }
    return tuple(audited), summary


def evaluate_risk_policy(
    proposal: CommitteeProposal,
    citation_audit: Dict[str, Any],
) -> RiskVerdictRecord:
    """Evaluate all hard deterministic risk policy rules and produce a PASS/VETO record."""
    policy = proposal.risk_policy
    pos = proposal.candidate_position
    metrics = compute_pro_forma_metrics(proposal)
    checks: List[RiskCheckResult] = []

    no_live_ok = (proposal.execution_mode == "PAPER") and (not policy.allow_live_execution)
    checks.append(
        RiskCheckResult(
            rule_id="NO_LIVE_EXECUTION",
            passed=no_live_ok,
            observed_value=proposal.execution_mode,
            limit_value="PAPER",
            unit="mode",
            message="Paper proposal only; live execution is permanently disabled.",
        )
    )

    not_restricted = pos.ticker not in policy.restricted_tickers
    checks.append(
        RiskCheckResult(
            rule_id="RESTRICTED_TICKER",
            passed=not_restricted,
            observed_value=pos.ticker,
            limit_value=list(policy.restricted_tickers),
            unit="ticker",
            message=(
                f"Ticker {pos.ticker} is permitted."
                if not_restricted
                else f"Ticker {pos.ticker} is on the restricted list."
            ),
        )
    )

    pos_wt = metrics["pro_forma_ticker_weight_pct"]
    checks.append(
        RiskCheckResult(
            rule_id="MAX_SINGLE_POSITION_WEIGHT_PCT",
            passed=pos_wt <= policy.max_single_position_weight_pct,
            observed_value=pos_wt,
            limit_value=policy.max_single_position_weight_pct,
            unit="pct",
            message=f"Pro-forma {pos.ticker} weight is {pos_wt:.2f}% vs limit {policy.max_single_position_weight_pct:.2f}%.",
        )
    )

    sec_wt = metrics["pro_forma_sector_weight_pct"]
    checks.append(
        RiskCheckResult(
            rule_id="MAX_SECTOR_WEIGHT_PCT",
            passed=sec_wt <= policy.max_sector_weight_pct,
            observed_value=sec_wt,
            limit_value=policy.max_sector_weight_pct,
            unit="pct",
            message=f"Pro-forma {pos.sector} sector weight is {sec_wt:.2f}% vs limit {policy.max_sector_weight_pct:.2f}%.",
        )
    )

    gross_pct = metrics["pro_forma_gross_exposure_pct"]
    checks.append(
        RiskCheckResult(
            rule_id="MAX_GROSS_EXPOSURE_PCT",
            passed=gross_pct <= policy.max_gross_exposure_pct,
            observed_value=gross_pct,
            limit_value=policy.max_gross_exposure_pct,
            unit="pct",
            message=f"Pro-forma gross exposure is {gross_pct:.2f}% vs limit {policy.max_gross_exposure_pct:.2f}%.",
        )
    )

    cash_pct = metrics["pro_forma_cash_reserve_pct"]
    checks.append(
        RiskCheckResult(
            rule_id="MIN_CASH_RESERVE_PCT",
            passed=cash_pct >= policy.min_cash_reserve_pct,
            observed_value=cash_pct,
            limit_value=policy.min_cash_reserve_pct,
            unit="pct",
            message=f"Pro-forma cash reserve is {cash_pct:.2f}% vs floor {policy.min_cash_reserve_pct:.2f}%.",
        )
    )

    var_pct = metrics["pro_forma_estimated_var_95_pct"]
    checks.append(
        RiskCheckResult(
            rule_id="MAX_ESTIMATED_VAR_95_PCT",
            passed=var_pct <= policy.max_estimated_var_95_pct,
            observed_value=var_pct,
            limit_value=policy.max_estimated_var_95_pct,
            unit="pct",
            message=f"Pro-forma 1-day 95% VaR is {var_pct:.4f}% vs limit {policy.max_estimated_var_95_pct:.2f}%.",
        )
    )

    adv_pct = metrics["adv_participation_pct"]
    checks.append(
        RiskCheckResult(
            rule_id="MAX_ADV_PARTICIPATION_PCT",
            passed=adv_pct <= policy.max_adv_participation_pct,
            observed_value=adv_pct,
            limit_value=policy.max_adv_participation_pct,
            unit="pct",
            message=f"Order ADV participation is {adv_pct:.2f}% vs limit {policy.max_adv_participation_pct:.2f}%.",
        )
    )

    fabricated_count = int(citation_audit.get("fabricated_citations", 0))
    checks.append(
        RiskCheckResult(
            rule_id="MAX_FABRICATED_CITATIONS",
            passed=fabricated_count <= policy.max_fabricated_citations,
            observed_value=fabricated_count,
            limit_value=policy.max_fabricated_citations,
            unit="count",
            message=f"Detected {fabricated_count} fabricated citation(s) vs max allowed {policy.max_fabricated_citations}.",
        )
    )

    verified_ratio = float(citation_audit.get("verified_citation_ratio", 0.0))
    checks.append(
        RiskCheckResult(
            rule_id="MIN_VERIFIED_CITATION_RATIO",
            passed=verified_ratio >= policy.min_verified_citation_ratio,
            observed_value=verified_ratio,
            limit_value=policy.min_verified_citation_ratio,
            unit="ratio",
            message=f"Verified citation ratio is {verified_ratio:.2f} vs floor {policy.min_verified_citation_ratio:.2f}.",
        )
    )

    violated = tuple(c.rule_id for c in checks if not c.passed)
    verdict = "VETO" if violated else "PASS"
    rationale = (
        f"Deterministic risk veto triggered by violated policy rule(s): {', '.join(violated)}."
        if violated
        else "All deterministic portfolio, liquidity, concentration, and evidence-integrity risk checks passed."
    )

    return RiskVerdictRecord(
        proposal_id=proposal.proposal_id,
        policy_id=policy.policy_id,
        verdict=verdict,
        non_overridable=(verdict == "VETO"),
        checks=tuple(checks),
        violated_rules=violated,
        metrics=metrics,
        rationale=rationale,
    )
