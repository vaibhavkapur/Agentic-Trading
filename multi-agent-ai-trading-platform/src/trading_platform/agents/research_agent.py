"""Read-only research agent adapters producing typed, evidence-backed ResearchReports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from trading_platform.domain.contracts import (
    AgentPermissionScope,
    FundamentalSnapshot,
    QuoteSnapshot,
    ResearchReport,
)
from trading_platform.domain.types import AgentRole, ResearchStance

if TYPE_CHECKING:
    from trading_platform.tools.gateway import BoundedToolGateway


class ResearchAgentAdapter(ABC):
    """Base contract for read-only research agents."""

    def __init__(self, agent_id: str, max_tool_calls: int = 6) -> None:
        self.scope = AgentPermissionScope(
            agent_id=agent_id,
            role=AgentRole.RESEARCH_AGENT,
            allowed_tools=["get_quote", "get_fundamentals", "get_news"],
            can_submit_orders=False,
            can_approve_orders=False,
            can_override_policy=False,
            max_tool_calls=max_tool_calls,
        )

    @property
    def agent_id(self) -> str:
        return self.scope.agent_id

    @abstractmethod
    def analyze(self, *, run_id: str, symbol: str, gateway: BoundedToolGateway) -> ResearchReport:
        """Analyze a symbol using only read-only tools and return a typed ResearchReport."""


class FundamentalResearchAgent(ResearchAgentAdapter):
    """Evaluates fundamentals, valuation, and untainted news sentiment."""

    def __init__(self, agent_id: str = "research-fundamental-v1", max_tool_calls: int = 6) -> None:
        super().__init__(agent_id=agent_id, max_tool_calls=max_tool_calls)

    def analyze(self, *, run_id: str, symbol: str, gateway: BoundedToolGateway) -> ResearchReport:
        quote_res = gateway.invoke(
            run_id=run_id, scope=self.scope, tool_name="get_quote", arguments={"symbol": symbol}
        )
        fund_res = gateway.invoke(
            run_id=run_id, scope=self.scope, tool_name="get_fundamentals", arguments={"symbol": symbol}
        )
        news_res = gateway.invoke(
            run_id=run_id,
            scope=self.scope,
            tool_name="get_news",
            arguments={"symbol": symbol, "limit": 5},
        )

        quote: QuoteSnapshot = quote_res.data
        fund: FundamentalSnapshot = fund_res.data
        news_items: list[dict] = news_res.data

        evidence_ids = [
            *(e.evidence_id for e in quote_res.evidence_items),
            *(e.evidence_id for e in fund_res.evidence_items),
            *(e.evidence_id for e in news_res.evidence_items),
        ]

        warnings: list[str] = []
        clean_sentiments: list[float] = []
        for item in news_items:
            if item["tainted"]:
                warnings.append(
                    f"Quarantined tainted news item {item['news_id']}: {', '.join(item['matched_rules'])}"
                )
            else:
                clean_sentiments.append(float(item["sentiment_score"]))

        # Deterministic fundamental + untainted news score
        avg_news = sum(clean_sentiments) / len(clean_sentiments) if clean_sentiments else 0.0
        growth_signal = min(max(fund.revenue_growth_yoy * 3.0, -0.5), 0.6)
        momentum_signal = min(max(fund.momentum_20d * 4.0, -0.4), 0.4)
        score = 0.45 * growth_signal + 0.25 * momentum_signal + 0.30 * avg_news

        if score >= 0.18:
            stance = ResearchStance.BULLISH
            fair_value = (quote.mid * Decimal("1.06")).quantize(Decimal("0.01"))
        elif score <= -0.15:
            stance = ResearchStance.BEARISH
            fair_value = (quote.mid * Decimal("0.94")).quantize(Decimal("0.01"))
        else:
            stance = ResearchStance.NEUTRAL
            fair_value = quote.mid.quantize(Decimal("0.01"))

        confidence = round(min(0.92, max(0.35, 0.50 + abs(score) * 0.5)), 3)
        thesis = (
            f"Fundamental analysis for {symbol}: rev_yoy={fund.revenue_growth_yoy:.1%}, "
            f"mom20d={fund.momentum_20d:.1%}, clean_news_avg={avg_news:.2f}, "
            f"composite_score={score:.3f} -> {stance.value}."
        )
        if warnings:
            thesis += f" ({len(warnings)} tainted news item(s) quarantined and excluded from scoring.)"

        return ResearchReport(
            report_id=f"RPT-{uuid4().hex[:10].upper()}",
            run_id=run_id,
            agent_id=self.agent_id,
            symbol=symbol,
            stance=stance,
            confidence=confidence,
            fair_value_usd=fair_value,
            thesis_summary=thesis,
            evidence_ids=evidence_ids,
            injection_warnings=warnings,
            created_at_utc=quote_res.call_record.timestamp_utc,
        )


class MomentumNewsResearchAgent(ResearchAgentAdapter):
    """Independent second research desk focused on short-horizon news sentiment and volatility."""

    def __init__(
        self,
        agent_id: str = "research-sentiment-v1",
        max_tool_calls: int = 6,
        focus_source: str | None = None,
    ) -> None:
        super().__init__(agent_id=agent_id, max_tool_calls=max_tool_calls)
        self._focus_source = focus_source

    def analyze(self, *, run_id: str, symbol: str, gateway: BoundedToolGateway) -> ResearchReport:
        quote_res = gateway.invoke(
            run_id=run_id, scope=self.scope, tool_name="get_quote", arguments={"symbol": symbol}
        )
        news_res = gateway.invoke(
            run_id=run_id,
            scope=self.scope,
            tool_name="get_news",
            arguments={"symbol": symbol, "limit": 5},
        )
        quote: QuoteSnapshot = quote_res.data
        news_items: list[dict] = news_res.data

        evidence_ids = [
            *(e.evidence_id for e in quote_res.evidence_items),
            *(e.evidence_id for e in news_res.evidence_items),
        ]

        warnings: list[str] = []
        relevant_scores: list[float] = []
        for item in news_items:
            if item["tainted"]:
                warnings.append(
                    f"Quarantined tainted news item {item['news_id']}: {', '.join(item['matched_rules'])}"
                )
                continue
            if self._focus_source is None or item["source"] == self._focus_source:
                relevant_scores.append(float(item["sentiment_score"]))

        if not relevant_scores:
            # Fall back to all untainted items if focused source had none
            relevant_scores = [float(i["sentiment_score"]) for i in news_items if not i["tainted"]]

        avg_sentiment = sum(relevant_scores) / len(relevant_scores) if relevant_scores else 0.0

        if avg_sentiment >= 0.25:
            stance = ResearchStance.BULLISH
            fair_value = (quote.mid * Decimal("1.04")).quantize(Decimal("0.01"))
        elif avg_sentiment <= -0.25:
            stance = ResearchStance.BEARISH
            fair_value = (quote.mid * Decimal("0.96")).quantize(Decimal("0.01"))
        else:
            stance = ResearchStance.NEUTRAL
            fair_value = quote.mid.quantize(Decimal("0.01"))

        confidence = round(min(0.90, max(0.35, 0.45 + abs(avg_sentiment) * 0.5)), 3)
        thesis = (
            f"Sentiment/momentum desk ({self._focus_source or 'ALL_CLEAN'}) for {symbol}: "
            f"untainted_items={len(relevant_scores)}, avg_sentiment={avg_sentiment:.2f} -> {stance.value}."
        )
        return ResearchReport(
            report_id=f"RPT-{uuid4().hex[:10].upper()}",
            run_id=run_id,
            agent_id=self.agent_id,
            symbol=symbol,
            stance=stance,
            confidence=confidence,
            fair_value_usd=fair_value,
            thesis_summary=thesis,
            evidence_ids=evidence_ids,
            injection_warnings=warnings,
            created_at_utc=quote_res.call_record.timestamp_utc,
        )
