"""Read-only portfolio agent adapter producing typed PortfolioProposals (never submits orders)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from trading_platform.domain.contracts import (
    AccountSnapshot,
    AgentPermissionScope,
    OrderIntent,
    PortfolioProposal,
    QuoteSnapshot,
    ResearchReport,
)
from trading_platform.domain.types import (
    AgentRole,
    OrderSide,
    OrderType,
    ResearchStance,
    TimeInForce,
)

if TYPE_CHECKING:
    from trading_platform.tools.gateway import BoundedToolGateway


class PortfolioAgentAdapter:
    """Translates consensus research + current portfolio state into a typed PortfolioProposal."""

    def __init__(
        self,
        agent_id: str = "portfolio-allocator-v1",
        max_tool_calls: int = 6,
        target_order_notional_usd: Decimal = Decimal("25000.00"),
    ) -> None:
        self.scope = AgentPermissionScope(
            agent_id=agent_id,
            role=AgentRole.PORTFOLIO_AGENT,
            allowed_tools=["get_account_state", "get_quote"],
            can_submit_orders=False,
            can_approve_orders=False,
            can_override_policy=False,
            max_tool_calls=max_tool_calls,
        )
        self._target_order_notional_usd = target_order_notional_usd

    @property
    def agent_id(self) -> str:
        return self.scope.agent_id

    def build_proposal(
        self,
        *,
        run_id: str,
        symbol: str,
        reports: list[ResearchReport],
        policy_version: str,
        gateway: BoundedToolGateway,
        override_quantity: int | None = None,
        override_limit_price: Decimal | None = None,
    ) -> PortfolioProposal | None:
        account_res = gateway.invoke(
            run_id=run_id,
            scope=self.scope,
            tool_name="get_account_state",
            arguments={},
        )
        quote_res = gateway.invoke(
            run_id=run_id,
            scope=self.scope,
            tool_name="get_quote",
            arguments={"symbol": symbol},
        )
        account: AccountSnapshot = account_res.data
        quote: QuoteSnapshot = quote_res.data

        stances = [r.stance for r in reports if r.stance != ResearchStance.NEUTRAL]
        if not stances:
            return None

        # Consensus direction (conflicts are already blocked upstream by orchestrator/policy)
        bullish_votes = sum(1 for s in stances if s == ResearchStance.BULLISH)
        bearish_votes = sum(1 for s in stances if s == ResearchStance.BEARISH)
        if bullish_votes == bearish_votes:
            return None

        side = OrderSide.BUY if bullish_votes > bearish_votes else OrderSide.SELL
        avg_conf = sum(r.confidence for r in reports) / len(reports)

        if side == OrderSide.BUY:
            reference_price = quote.ask
            limit_price = override_limit_price or (quote.ask * Decimal("1.002")).quantize(
                Decimal("0.01")
            )
            desired_notional = (self._target_order_notional_usd * Decimal(str(round(avg_conf, 2)))).quantize(
                Decimal("0.01")
            )
            qty = override_quantity or max(1, int(desired_notional // reference_price))
        else:
            existing_pos = account.positions.get(symbol)
            if existing_pos is None or existing_pos.quantity == 0:
                # No inventory to sell (prototype forbids naked shorting)
                return None
            reference_price = quote.bid
            limit_price = override_limit_price or (quote.bid * Decimal("0.998")).quantize(
                Decimal("0.01")
            )
            qty = override_quantity or max(1, min(existing_pos.quantity, existing_pos.quantity // 2 or 1))

        notional = (limit_price * Decimal(qty)).quantize(Decimal("0.01"))
        all_evidence = sorted(
            {
                *(ev_id for r in reports for ev_id in r.evidence_ids),
                *(e.evidence_id for e in account_res.evidence_items),
                *(e.evidence_id for e in quote_res.evidence_items),
            }
        )

        intent = OrderIntent(
            account_id=account.account_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            currency=quote.currency,
        )

        return PortfolioProposal(
            proposal_id=f"PROP-{uuid4().hex[:10].upper()}",
            run_id=run_id,
            agent_id=self.agent_id,
            policy_version=policy_version,
            order_intent=intent,
            reference_price_usd=reference_price,
            estimated_notional_usd=notional,
            rationale=(
                f"Proposed {side.value} {qty} {symbol} @ LIMIT {limit_price} {quote.currency} "
                f"(est. notional ${notional}) based on {len(reports)} research report(s) "
                f"with avg confidence {avg_conf:.2f}."
            ),
            research_report_ids=[r.report_id for r in reports],
            evidence_ids=all_evidence,
            created_at_utc=quote_res.call_record.timestamp_utc,
        )
