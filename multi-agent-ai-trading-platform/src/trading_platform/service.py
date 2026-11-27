"""Top-level TradingPlatform service facade wiring agents, orchestrator, policy, approvals, OMS, and persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_platform.agents.portfolio_agent import PortfolioAgentAdapter
from trading_platform.agents.research_agent import (
    FundamentalResearchAgent,
    MomentumNewsResearchAgent,
    ResearchAgentAdapter,
)
from trading_platform.agents.risk_agent import IndependentRiskService
from trading_platform.domain.config import PlatformConfig
from trading_platform.domain.contracts import (
    AccountSnapshot,
    ApprovalDecision,
    ApprovalRequest,
    FillRecord,
    OrderIntent,
    OrderRecord,
)
from trading_platform.domain.types import ApprovalStatus, ExecutionMode
from trading_platform.execution.broker import SimulatedPaperBroker
from trading_platform.execution.oms import IdempotentOMS
from trading_platform.orchestrator.engine import MultiAgentOrchestrator, OrchestrationOutcome
from trading_platform.policy.approvals import ExactActionApprovalService
from trading_platform.policy.engine import PolicyEngine
from trading_platform.storage.event_bus import EventBus
from trading_platform.storage.repository import StateRepository
from trading_platform.tools.gateway import BoundedToolGateway
from trading_platform.tools.market_tools import MarketDataProvider


def default_project_root() -> Path:
    """Resolve repository root relative to this source file."""
    return Path(__file__).resolve().parents[2]


class TradingPlatform:
    """Composable local/paper control plane supporting durable SQLite state and clean restart recovery."""

    def __init__(
        self,
        *,
        config: PlatformConfig,
        market_data: MarketDataProvider,
        repository: StateRepository | None = None,
        broker: SimulatedPaperBroker | None = None,
        research_agents: list[ResearchAgentAdapter] | None = None,
        portfolio_agent: PortfolioAgentAdapter | None = None,
    ) -> None:
        self.config = config
        self.market_data = market_data
        self.repository = repository or StateRepository(":memory:")
        self.event_bus = EventBus(persist_callback=self.repository.save_event)

        # Initialize persisted account snapshot and execution mode only if not already persisted (restart-safe)
        if self.repository.load_account_snapshot() is None:
            self.repository.save_account_snapshot(market_data.initial_account)
        if self.repository.get_state_value("execution_mode") is None:
            self.repository.set_execution_mode(config.policy.execution_mode)
        if self.repository.get_state_value("kill_switch") is None:
            self.repository.set_kill_switch(False)

        self.policy_engine = PolicyEngine(config.policy)
        self.risk_service = IndependentRiskService(
            policy=config.policy,
            limits=config.risk_limits,
        )
        self.approval_service = ExactActionApprovalService(
            policy=config.policy,
            repository=self.repository,
            event_bus=self.event_bus,
        )
        self.tool_gateway = BoundedToolGateway(
            market_data=self.market_data,
            repository=self.repository,
            event_bus=self.event_bus,
            policy_version=config.policy.policy_version,
            max_total_tool_calls=config.orchestrator.max_total_tool_calls,
        )
        self.research_agents: list[ResearchAgentAdapter] = research_agents or [
            FundamentalResearchAgent(
                agent_id="research-fundamental-v1",
                max_tool_calls=config.orchestrator.max_tool_calls_per_agent,
            ),
            MomentumNewsResearchAgent(
                agent_id="research-sentiment-v1",
                max_tool_calls=config.orchestrator.max_tool_calls_per_agent,
            ),
        ]
        self.portfolio_agent = portfolio_agent or PortfolioAgentAdapter(
            agent_id="portfolio-allocator-v1",
            max_tool_calls=config.orchestrator.max_tool_calls_per_agent,
        )
        self.orchestrator = MultiAgentOrchestrator(
            config=config,
            repository=self.repository,
            event_bus=self.event_bus,
            market_data=self.market_data,
            tool_gateway=self.tool_gateway,
            research_agents=self.research_agents,
            portfolio_agent=self.portfolio_agent,
            risk_service=self.risk_service,
            policy_engine=self.policy_engine,
            approval_service=self.approval_service,
        )
        self.broker = broker or SimulatedPaperBroker()
        self.oms = IdempotentOMS(
            repository=self.repository,
            event_bus=self.event_bus,
            market_data=self.market_data,
            risk_service=self.risk_service,
            approval_service=self.approval_service,
            broker=self.broker,
            policy_version=config.policy.policy_version,
        )

    @classmethod
    def from_project_root(
        cls,
        root: Path | None = None,
        *,
        db_path: Path | str = ":memory:",
        clock: Callable[[], datetime] | None = None,
        broker: SimulatedPaperBroker | None = None,
        research_agents: list[ResearchAgentAdapter] | None = None,
    ) -> TradingPlatform:
        project_root = root or default_project_root()
        config = PlatformConfig.from_file(project_root / "config" / "platform_config.json")
        market_data = MarketDataProvider.from_fixtures(
            project_root / "data" / "fixtures" / "market_data.json",
            project_root / "data" / "fixtures" / "news_feed.json",
            clock=clock,
        )
        repo = StateRepository(db_path)
        return cls(
            config=config,
            market_data=market_data,
            repository=repo,
            broker=broker,
            research_agents=research_agents,
        )

    def close(self) -> None:
        self.repository.close()

    # --- Operational Controls ---

    def set_execution_mode(self, *, mode: str, actor_id: str, reason: str = "Operator mode update") -> ExecutionMode:
        validated = self.policy_engine.validate_execution_mode_change(
            requested_mode=mode,
            actor_id=actor_id,
        )
        self.repository.set_execution_mode(validated)
        now_utc = self.market_data.now()
        self.repository.append_audit(
            actor_id=actor_id,
            actor_role=self.config.policy.authorized_approvers[actor_id],
            action="SET_EXECUTION_MODE",
            outcome=validated.value,
            policy_version=self.config.policy.policy_version,
            payload={"execution_mode": validated.value, "reason": reason},
            timestamp_utc=now_utc,
        )
        self.event_bus.publish(
            event_type="controls.execution_mode_changed",
            policy_version=self.config.policy.policy_version,
            payload={"execution_mode": validated.value, "actor_id": actor_id, "reason": reason},
        )
        return validated

    def set_kill_switch(self, *, active: bool, actor_id: str, reason: str = "Operator kill switch toggle") -> bool:
        self.policy_engine.validate_execution_mode_change(
            requested_mode=self.repository.get_execution_mode().value,
            actor_id=actor_id,
        )
        self.repository.set_kill_switch(active)
        now_utc = self.market_data.now()
        self.repository.append_audit(
            actor_id=actor_id,
            actor_role=self.config.policy.authorized_approvers[actor_id],
            action="SET_KILL_SWITCH",
            outcome="ACTIVE" if active else "INACTIVE",
            policy_version=self.config.policy.policy_version,
            payload={"active": active, "reason": reason},
            timestamp_utc=now_utc,
        )
        self.event_bus.publish(
            event_type="controls.kill_switch_changed",
            policy_version=self.config.policy.policy_version,
            payload={"active": active, "actor_id": actor_id, "reason": reason},
        )
        return active

    # --- Core Workflows ---

    def run_cycle(
        self,
        *,
        symbol: str,
        override_quantity: int | None = None,
        override_limit_price: Decimal | None = None,
        approval_ttl_seconds: int | None = None,
    ) -> OrchestrationOutcome:
        return self.orchestrator.run_cycle(
            symbol=symbol,
            override_quantity=override_quantity,
            override_limit_price=override_limit_price,
            approval_ttl_seconds=approval_ttl_seconds,
        )

    def decide_approval(
        self,
        *,
        approval_id: str,
        actor_id: str,
        approve: bool,
        expected_action_hash: str,
        reason: str,
    ) -> ApprovalRequest:
        return self.approval_service.decide(
            approval_id=approval_id,
            decision=ApprovalDecision(
                actor_id=actor_id,
                approve=approve,
                expected_action_hash=expected_action_hash,
                reason=reason,
            ),
            now_utc=self.market_data.now(),
        )

    def dispatch_order(
        self,
        *,
        approval_id: str,
        idempotency_key: str,
        actor_id: str = "OMS_DISPATCHER",
        order_intent_override: OrderIntent | None = None,
    ) -> OrderRecord:
        return self.oms.dispatch_approved_order(
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            order_intent_override=order_intent_override,
        )

    def ingest_fill(self, fill: FillRecord) -> tuple[OrderRecord, bool]:
        return self.oms.ingest_fill(fill)

    def get_account_snapshot(self) -> AccountSnapshot:
        return self.repository.load_account_snapshot() or self.market_data.initial_account

    def get_run_provenance(self, run_id: str) -> dict[str, Any] | None:
        run = self.repository.get_run(run_id)
        if run is None:
            return None
        proposal = self.repository.get_proposal(run.proposal_id) if run.proposal_id else None
        risk_assessments = (
            self.repository.list_risk_assessments_for_proposal(proposal.proposal_id)
            if proposal
            else []
        )
        approval = self.repository.get_approval(run.approval_id) if run.approval_id else None
        order = self.repository.get_order(run.order_id) if run.order_id else None
        fills = self.repository.list_fills_for_order(order.order_id) if order else []
        return {
            "run": run.model_dump(mode="json"),
            "evidence": [e.model_dump(mode="json") for e in self.repository.list_evidence_for_run(run_id)],
            "tool_calls": [t.model_dump(mode="json") for t in self.repository.list_tool_calls_for_run(run_id)],
            "research_reports": [r.model_dump(mode="json") for r in self.repository.list_research_reports_for_run(run_id)],
            "conflicts": [c.model_dump(mode="json") for c in self.repository.list_conflicts_for_run(run_id)],
            "proposal": proposal.model_dump(mode="json") if proposal else None,
            "risk_assessments": [ra.model_dump(mode="json") for ra in risk_assessments],
            "approval": approval.model_dump(mode="json") if approval else None,
            "order": order.model_dump(mode="json") if order else None,
            "fills": [f.model_dump(mode="json") for f in fills],
        }

    def get_metrics(self) -> dict[str, Any]:
        runs = self.repository.list_runs(limit=1000)
        approvals = self.repository.list_approvals()
        orders = self.repository.list_orders(limit=1000)
        fills = self.repository.list_fills(limit=1000)
        chain_valid, audit_count, chain_error = self.repository.verify_audit_chain()
        return {
            "policy_version": self.config.policy.policy_version,
            "config_version": self.config.config_version,
            "execution_mode": self.repository.get_execution_mode().value,
            "kill_switch_active": self.repository.get_kill_switch(),
            "total_runs": len(runs),
            "pending_approvals": sum(1 for a in approvals if a.status == ApprovalStatus.PENDING),
            "approved_approvals": sum(1 for a in approvals if a.status == ApprovalStatus.APPROVED),
            "consumed_approvals": sum(1 for a in approvals if a.status == ApprovalStatus.CONSUMED),
            "total_orders": len(orders),
            "total_fills": len(fills),
            "audit_entries": audit_count,
            "audit_chain_valid": chain_valid,
            "audit_chain_error": chain_error,
        }
