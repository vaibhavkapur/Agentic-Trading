"""Bounded multi-agent orchestrator coordinating Research -> Conflict Check -> Portfolio -> Risk -> Policy -> Approval."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

from trading_platform.agents.portfolio_agent import PortfolioAgentAdapter
from trading_platform.agents.research_agent import ResearchAgentAdapter
from trading_platform.agents.risk_agent import IndependentRiskService
from trading_platform.domain.config import PlatformConfig
from trading_platform.domain.contracts import (
    ApprovalRequest,
    ConflictRecord,
    PortfolioProposal,
    ResearchReport,
    RiskAssessment,
    RunRecord,
)
from trading_platform.domain.types import (
    PolicyDecisionStatus,
    ResearchStance,
    RiskStatus,
    RunStatus,
)
from trading_platform.policy.approvals import ExactActionApprovalService
from trading_platform.policy.engine import PolicyEngine
from trading_platform.storage.event_bus import EventBus
from trading_platform.storage.repository import StateRepository
from trading_platform.tools.gateway import BoundedToolGateway
from trading_platform.tools.market_tools import MarketDataProvider


@dataclass
class OrchestrationOutcome:
    run: RunRecord
    research_reports: list[ResearchReport] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    proposal: PortfolioProposal | None = None
    risk_assessment: RiskAssessment | None = None
    approval_request: ApprovalRequest | None = None


class MultiAgentOrchestrator:
    """Coordinates read-only agents and deterministic gates; never submits orders directly."""

    def __init__(
        self,
        *,
        config: PlatformConfig,
        repository: StateRepository,
        event_bus: EventBus,
        market_data: MarketDataProvider,
        tool_gateway: BoundedToolGateway,
        research_agents: list[ResearchAgentAdapter],
        portfolio_agent: PortfolioAgentAdapter,
        risk_service: IndependentRiskService,
        policy_engine: PolicyEngine,
        approval_service: ExactActionApprovalService,
    ) -> None:
        self._config = config
        self._repository = repository
        self._event_bus = event_bus
        self._market_data = market_data
        self._tool_gateway = tool_gateway
        self._research_agents = research_agents
        self._portfolio_agent = portfolio_agent
        self._risk_service = risk_service
        self._policy_engine = policy_engine
        self._approval_service = approval_service

    def run_cycle(
        self,
        *,
        symbol: str,
        override_quantity: int | None = None,
        override_limit_price: Decimal | None = None,
        approval_ttl_seconds: int | None = None,
    ) -> OrchestrationOutcome:
        sym = symbol.strip().upper()
        now_utc = self._market_data.now()
        run_id = f"RUN-{uuid4().hex[:10].upper()}"
        policy_version = self._policy_engine.policy_version

        run = RunRecord(
            run_id=run_id,
            symbol=sym,
            policy_version=policy_version,
            config_version=self._config.config_version,
            status=RunStatus.RUNNING,
            started_at_utc=now_utc,
        )
        self._repository.save_run(run)
        self._repository.append_audit(
            actor_id="ORCHESTRATOR",
            actor_role="ORCHESTRATOR",
            action="RUN_STARTED",
            outcome="RUNNING",
            policy_version=policy_version,
            run_id=run_id,
            entity_type="run",
            entity_id=run_id,
            payload={"symbol": sym, "config_version": self._config.config_version},
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="orchestrator.run_started",
            policy_version=policy_version,
            run_id=run_id,
            payload={"symbol": sym},
        )

        steps_used = 0
        max_steps = self._config.orchestrator.max_steps_per_run

        # Step 1: Execute read-only research agents within step & tool budgets
        reports: list[ResearchReport] = []
        for agent in self._research_agents:
            steps_used += 1
            if steps_used > max_steps:
                return self._finalize_run(
                    run=run,
                    status=RunStatus.FAILED,
                    summary=f"Exceeded max_steps_per_run={max_steps}.",
                    reports=reports,
                    conflicts=[],
                )
            report = agent.analyze(run_id=run_id, symbol=sym, gateway=self._tool_gateway)
            reports.append(report)
            self._repository.save_research_report(report)
            self._repository.append_audit(
                actor_id=agent.agent_id,
                actor_role="RESEARCH_AGENT",
                action="RESEARCH_REPORT_PUBLISHED",
                outcome=report.stance.value,
                policy_version=policy_version,
                run_id=run_id,
                entity_type="research_report",
                entity_id=report.report_id,
                evidence_ids=report.evidence_ids,
                payload={
                    "symbol": sym,
                    "confidence": report.confidence,
                    "injection_warnings": report.injection_warnings,
                },
                timestamp_utc=now_utc,
            )

        # Step 2: Detect directional conflicts across research agents
        non_neutral = {r.agent_id: r.stance for r in reports if r.stance != ResearchStance.NEUTRAL}
        unique_stances = set(non_neutral.values())
        conflicts: list[ConflictRecord] = []
        if ResearchStance.BULLISH in unique_stances and ResearchStance.BEARISH in unique_stances:
            conflict = ConflictRecord(
                conflict_id=f"CONF-{uuid4().hex[:10].upper()}",
                run_id=run_id,
                symbol=sym,
                agent_ids=list(non_neutral.keys()),
                stances=non_neutral,
                resolution=self._config.policy.conflict_resolution_mode.value,
                blocked_execution=(
                    self._config.policy.conflict_resolution_mode.value == "BLOCK_AND_ESCALATE"
                ),
                details=(
                    f"Direct directional conflict on {sym}: "
                    + ", ".join(f"{aid}={st.value}" for aid, st in non_neutral.items())
                ),
                created_at_utc=now_utc,
            )
            conflicts.append(conflict)
            self._repository.save_conflict(conflict)
            policy_conflict = self._policy_engine.evaluate_conflict(conflict)
            self._repository.append_audit(
                actor_id="POLICY_ENGINE",
                actor_role="POLICY_ENGINE",
                action="CONFLICT_DETECTED",
                outcome=policy_conflict.reason_code,
                policy_version=policy_version,
                run_id=run_id,
                entity_type="conflict",
                entity_id=conflict.conflict_id,
                evidence_ids=sorted({ev for r in reports for ev in r.evidence_ids}),
                payload={"stances": {k: v.value for k, v in non_neutral.items()}},
                timestamp_utc=now_utc,
            )
            self._event_bus.publish(
                event_type="orchestrator.conflict_detected",
                policy_version=policy_version,
                run_id=run_id,
                payload={
                    "conflict_id": conflict.conflict_id,
                    "symbol": sym,
                    "resolution": conflict.resolution,
                },
            )
            if policy_conflict.status == PolicyDecisionStatus.CONFLICT_ESCALATED:
                return self._finalize_run(
                    run=run,
                    status=RunStatus.BLOCKED_CONFLICT,
                    summary=policy_conflict.message,
                    reports=reports,
                    conflicts=conflicts,
                )

        # Step 3: Read-only portfolio agent builds typed proposal (cannot execute)
        steps_used += 1
        proposal = self._portfolio_agent.build_proposal(
            run_id=run_id,
            symbol=sym,
            reports=reports,
            policy_version=policy_version,
            gateway=self._tool_gateway,
            override_quantity=override_quantity,
            override_limit_price=override_limit_price,
        )
        if proposal is None:
            return self._finalize_run(
                run=run,
                status=RunStatus.COMPLETED_NO_ACTION,
                summary=f"No actionable order proposed for {sym} (neutral thesis or no inventory to sell).",
                reports=reports,
                conflicts=conflicts,
            )

        self._repository.save_proposal(proposal)
        self._repository.append_audit(
            actor_id=self._portfolio_agent.agent_id,
            actor_role="PORTFOLIO_AGENT",
            action="PROPOSAL_CREATED",
            outcome="SUBMITTED_TO_RISK",
            policy_version=policy_version,
            run_id=run_id,
            entity_type="proposal",
            entity_id=proposal.proposal_id,
            evidence_ids=proposal.evidence_ids,
            payload={
                "symbol": sym,
                "side": proposal.order_intent.side.value,
                "quantity": proposal.order_intent.quantity,
                "limit_price": str(proposal.order_intent.limit_price),
                "exact_action_hash": proposal.exact_action_hash(),
            },
            timestamp_utc=now_utc,
        )

        # Step 4: Independent Pre-Approval Risk Assessment
        steps_used += 1
        account = self._repository.load_account_snapshot() or self._market_data.initial_account
        risk_assessment = self._risk_service.evaluate(
            proposal=proposal,
            account=account,
            quotes=self._market_data.get_all_quotes(),
            now_utc=now_utc,
            stage="PRE_APPROVAL",
        )
        self._repository.save_risk_assessment(risk_assessment)
        self._repository.append_audit(
            actor_id="RISK_SERVICE",
            actor_role="RISK_SERVICE",
            action="PRE_APPROVAL_RISK_CHECK",
            outcome=risk_assessment.status.value,
            policy_version=policy_version,
            run_id=run_id,
            entity_type="risk_assessment",
            entity_id=risk_assessment.assessment_id,
            evidence_ids=proposal.evidence_ids,
            payload={
                "proposal_id": proposal.proposal_id,
                "failed_checks": [c.code for c in risk_assessment.failed_checks],
            },
            timestamp_utc=now_utc,
        )

        # Step 5: Deterministic Policy Engine (final authority)
        steps_used += 1
        policy_result = self._policy_engine.evaluate_proposal(
            proposal=proposal,
            risk_assessment=risk_assessment,
        )
        if policy_result.status != PolicyDecisionStatus.PENDING_APPROVAL:
            blocked_status = (
                RunStatus.BLOCKED_RISK
                if risk_assessment.status != RiskStatus.APPROVED
                else RunStatus.BLOCKED_POLICY
            )
            self._repository.append_audit(
                actor_id="POLICY_ENGINE",
                actor_role="POLICY_ENGINE",
                action="POLICY_EVALUATION",
                outcome=policy_result.reason_code,
                policy_version=policy_version,
                run_id=run_id,
                entity_type="proposal",
                entity_id=proposal.proposal_id,
                evidence_ids=proposal.evidence_ids,
                payload={"message": policy_result.message},
                timestamp_utc=now_utc,
            )
            return self._finalize_run(
                run=run,
                status=blocked_status,
                summary=policy_result.message,
                reports=reports,
                conflicts=conflicts,
                proposal=proposal,
                risk_assessment=risk_assessment,
            )

        # Step 6: Create exact-action human approval request (never auto-executes)
        approval_request = self._approval_service.create_request(
            proposal=proposal,
            risk_assessment_id=risk_assessment.assessment_id,
            now_utc=now_utc,
            ttl_seconds=approval_ttl_seconds,
        )
        return self._finalize_run(
            run=run,
            status=RunStatus.AWAITING_APPROVAL,
            summary=(
                f"Proposal {proposal.proposal_id} passed pre-approval risk and policy; "
                f"awaiting exact-action approval {approval_request.approval_id}."
            ),
            reports=reports,
            conflicts=conflicts,
            proposal=proposal,
            risk_assessment=risk_assessment,
            approval_request=approval_request,
        )

    def _finalize_run(
        self,
        *,
        run: RunRecord,
        status: RunStatus,
        summary: str,
        reports: list[ResearchReport],
        conflicts: list[ConflictRecord],
        proposal: PortfolioProposal | None = None,
        risk_assessment: RiskAssessment | None = None,
        approval_request: ApprovalRequest | None = None,
    ) -> OrchestrationOutcome:
        now_utc = self._market_data.now()
        evidence_items = self._repository.list_evidence_for_run(run.run_id)
        updated = run.model_copy(
            update={
                "status": status,
                "completed_at_utc": now_utc,
                "tool_calls_used": self._tool_gateway.get_run_tool_call_count(run.run_id),
                "evidence_ids": [e.evidence_id for e in evidence_items],
                "research_report_ids": [r.report_id for r in reports],
                "conflict_ids": [c.conflict_id for c in conflicts],
                "proposal_id": proposal.proposal_id if proposal else None,
                "pre_approval_risk_id": risk_assessment.assessment_id if risk_assessment else None,
                "approval_id": approval_request.approval_id if approval_request else None,
                "summary": summary,
            }
        )
        self._repository.save_run(updated)
        self._event_bus.publish(
            event_type="orchestrator.run_completed",
            policy_version=updated.policy_version,
            run_id=updated.run_id,
            payload={"status": status.value, "summary": summary},
        )
        return OrchestrationOutcome(
            run=updated,
            research_reports=reports,
            conflicts=conflicts,
            proposal=proposal,
            risk_assessment=risk_assessment,
            approval_request=approval_request,
        )
