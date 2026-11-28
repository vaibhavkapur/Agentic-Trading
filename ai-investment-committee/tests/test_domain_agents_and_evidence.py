"""Domain tests: reference oracle, agent disagreement, fabricated evidence, and tool isolation."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_investment_committee.agents import AdapterResponse, DeterministicMockAdapter
from ai_investment_committee.errors import (
    BudgetExceededError,
    NoExecutionCapabilityError,
    ToolAccessDeniedError,
)
from ai_investment_committee.models import (
    AgentBudget,
    Claim,
    CommitteeConfig,
    CommitteeProposal,
    ThesisRecord,
)
from ai_investment_committee.replay import compare_to_baseline, evaluate_deliberation
from ai_investment_committee.state_machine import run_deliberation
from ai_investment_committee.tools import RoleToolSandbox

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


class FabricatingBullAdapter(DeterministicMockAdapter):
    """Test adapter that emits a fabricated evidence citation alongside a real one."""

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
        fabricated_claim = Claim(
            claim_id="BULL-FAB-99",
            author_role="bull",
            statement="Synthetic claim citing non-existent audit report EV-FAKE-999.",
            evidence_ids=("EV-FAKE-999",),
            is_uncertain=False,
            citation_status="VERIFIED",
        )
        return AdapterResponse(
            summary=base.summary + " (with unverified citation attempt)",
            claims=base.claims + (fabricated_claim,),
            score=base.score,
            tokens_used=base.tokens_used,
            latency_ms=base.latency_ms,
            cost_usd=base.cost_usd,
        )


class TestDomainAgentsAndEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CommitteeConfig.model_validate(
            json.loads((CONFIG_DIR / "committee_default.json").read_text())
        )
        self.ref_proposal = CommitteeProposal.model_validate(
            json.loads((FIXTURES_DIR / "valid_reference_proposal.json").read_text())
        )
        self.ref_oracle = json.loads((FIXTURES_DIR / "reference_expected_output.json").read_text())
        self.disagree_proposal = CommitteeProposal.model_validate(
            json.loads((FIXTURES_DIR / "disagreement_fabricated_evidence.json").read_text())
        )

    def test_reference_proposal_matches_independent_oracle(self) -> None:
        trace = run_deliberation(proposal=self.ref_proposal, config=self.config)
        comparison = compare_to_baseline(trace=trace, oracle=self.ref_oracle)
        self.assertTrue(comparison["passed"], msg=json.dumps(comparison, indent=2))
        self.assertTrue(comparison["all_metrics_within_tolerance"])
        self.assertTrue(comparison["verdict_match"])
        self.assertTrue(comparison["invariants_match"])

    def test_agent_disagreement_records_high_dissent(self) -> None:
        trace = run_deliberation(proposal=self.disagree_proposal, config=self.config)
        metrics = evaluate_deliberation(trace)

        self.assertEqual(trace.decision.challenge.dissent_level, "HIGH")
        self.assertGreaterEqual(trace.decision.challenge.dissent_score, 0.70)
        self.assertTrue(metrics.dissent_present)
        self.assertGreater(len(trace.decision.challenge.challenged_claim_ids), 0)
        self.assertTrue(metrics.all_claims_cited_or_uncertain)
        self.assertEqual(metrics.unsupported_claims, 0)

    def test_fabricated_evidence_detected_marked_uncertain_and_vetoed(self) -> None:
        trace = run_deliberation(
            proposal=self.disagree_proposal,
            config=self.config,
            adapter=FabricatingBullAdapter(),
        )
        metrics = evaluate_deliberation(trace)

        fab_claims = [
            c for c in trace.decision.thesis.claims if c.claim_id == "BULL-FAB-99"
        ]
        self.assertEqual(len(fab_claims), 1)
        fab = fab_claims[0]
        self.assertEqual(fab.citation_status, "FABRICATED")
        self.assertTrue(fab.is_uncertain)
        self.assertIn("EV-FAKE-999", fab.fabricated_evidence_ids)
        self.assertEqual(fab.evidence_ids, ())
        self.assertIn("EV-FAKE-999", fab.uncertainty_reason or "")

        # Deterministic risk policy vetoes fabricated citations.
        self.assertEqual(trace.decision.risk_verdict.verdict, "VETO")
        self.assertIn("MAX_FABRICATED_CITATIONS", trace.decision.risk_verdict.violated_rules)
        self.assertEqual(trace.decision.status, "VETOED")
        self.assertEqual(metrics.fabricated_citations, 1)
        self.assertTrue(metrics.all_claims_cited_or_uncertain)

    def test_role_tool_isolation_and_no_execution_capability(self) -> None:
        budget = self.config.agent_budgets["bull"]
        bull_sandbox = RoleToolSandbox(
            role="bull",
            proposal=self.ref_proposal,
            budget=budget,
        )
        with self.assertRaises(ToolAccessDeniedError):
            bull_sandbox.invoke("get_risk_policy")
        with self.assertRaises(ToolAccessDeniedError):
            bull_sandbox.invoke("get_portfolio_state")
        with self.assertRaises(NoExecutionCapabilityError):
            bull_sandbox.invoke("submit_order", {"ticker": "ACME", "qty": 100})
        with self.assertRaises(NoExecutionCapabilityError):
            bull_sandbox.invoke("override_risk_veto")

        portfolio_sandbox = RoleToolSandbox(
            role="portfolio",
            proposal=self.ref_proposal,
            budget=self.config.agent_budgets["portfolio"],
        )
        with self.assertRaises(ToolAccessDeniedError):
            portfolio_sandbox.invoke("get_research_briefs")

    def test_fixed_budget_enforcement(self) -> None:
        tiny_budget = AgentBudget(
            max_tool_calls=1,
            max_tokens=100,
            max_latency_ms=1000,
            max_cost_usd=0.05,
        )
        sandbox = RoleToolSandbox(role="bull", proposal=self.ref_proposal, budget=tiny_budget)
        sandbox.invoke("get_candidate_position")
        with self.assertRaises(BudgetExceededError):
            sandbox.invoke("get_research_briefs")


if __name__ == "__main__":
    unittest.main()
