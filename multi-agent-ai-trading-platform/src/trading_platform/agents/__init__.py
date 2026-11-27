"""Research, portfolio, and independent risk agent adapters plus prompt-injection defense."""

from trading_platform.agents.base import InjectionScanResult, PromptInjectionGuard
from trading_platform.agents.portfolio_agent import PortfolioAgentAdapter
from trading_platform.agents.research_agent import (
    FundamentalResearchAgent,
    MomentumNewsResearchAgent,
    ResearchAgentAdapter,
)
from trading_platform.agents.risk_agent import IndependentRiskService

__all__ = [
    "FundamentalResearchAgent",
    "IndependentRiskService",
    "InjectionScanResult",
    "MomentumNewsResearchAgent",
    "PortfolioAgentAdapter",
    "PromptInjectionGuard",
    "ResearchAgentAdapter",
]
