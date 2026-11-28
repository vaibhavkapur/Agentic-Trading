"""Agent adapter protocol and offline reference/stochastic/faulty agents."""

from __future__ import annotations

from fin_eval.agents.base import FinancialAgentAdapter, OptionalLLMProviderAdapter
from fin_eval.agents.mock_agents import (
    FaultyDemoAgent,
    ReferenceCompliantAgent,
    StochasticFinancialAgent,
    build_agent_from_config,
)

__all__ = [
    "FinancialAgentAdapter",
    "OptionalLLMProviderAdapter",
    "ReferenceCompliantAgent",
    "StochasticFinancialAgent",
    "FaultyDemoAgent",
    "build_agent_from_config",
]
