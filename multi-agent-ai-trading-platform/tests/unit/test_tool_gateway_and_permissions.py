"""Unit tests for BoundedToolGateway permissions, call budgets, and argument sanitization."""

from __future__ import annotations

import pytest

from trading_platform.domain.contracts import AgentPermissionScope
from trading_platform.domain.errors import ToolAccessError
from trading_platform.domain.types import AgentRole
from trading_platform.service import TradingPlatform


def test_agent_cannot_invoke_submit_order_tool(platform: TradingPlatform) -> None:
    scope = platform.portfolio_agent.scope
    with pytest.raises(ToolAccessError) as exc_info:
        platform.tool_gateway.invoke(
            run_id="RUN-TEST-1",
            scope=scope,
            tool_name="submit_order",
            arguments={"symbol": "AAPL", "quantity": 100},
        )
    assert exc_info.value.code == "AGENT_EXECUTION_FORBIDDEN"
    calls = platform.repository.list_tool_calls_for_run("RUN-TEST-1")
    assert len(calls) == 1
    assert calls[0].allowed is False
    assert calls[0].error_code == "AGENT_EXECUTION_FORBIDDEN"


def test_tool_gateway_enforces_per_agent_call_budget(platform: TradingPlatform) -> None:
    tight_scope = AgentPermissionScope(
        agent_id="tight-agent",
        role=AgentRole.RESEARCH_AGENT,
        allowed_tools=["get_quote"],
        max_tool_calls=2,
    )
    platform.tool_gateway.invoke(
        run_id="RUN-BUDGET", scope=tight_scope, tool_name="get_quote", arguments={"symbol": "AAPL"}
    )
    platform.tool_gateway.invoke(
        run_id="RUN-BUDGET", scope=tight_scope, tool_name="get_quote", arguments={"symbol": "MSFT"}
    )
    with pytest.raises(ToolAccessError) as exc_info:
        platform.tool_gateway.invoke(
            run_id="RUN-BUDGET",
            scope=tight_scope,
            tool_name="get_quote",
            arguments={"symbol": "NVDA"},
        )
    assert exc_info.value.code == "AGENT_TOOL_BUDGET_EXCEEDED"


def test_tool_gateway_rejects_malicious_arguments(platform: TradingPlatform) -> None:
    scope = platform.research_agents[0].scope
    for bad_args in [
        {"symbol": "AAPL; DROP TABLE orders--"},
        {"symbol": "../../etc/passwd"},
        {"symbol": "AAPL$(rm -rf /)"},
        {"symbol": "AAPL", "unexpected": "inject"},
    ]:
        with pytest.raises(ToolAccessError) as exc_info:
            platform.tool_gateway.invoke(
                run_id="RUN-MAL",
                scope=scope,
                tool_name="get_quote",
                arguments=bad_args,
            )
        assert exc_info.value.code in {"MALICIOUS_TOOL_ARGUMENTS", "INVALID_TOOL_ARGUMENTS"}
