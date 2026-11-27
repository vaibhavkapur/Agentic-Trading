"""Unit tests for M1 domain contracts, config invariants, and exact-action hashing."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_platform.domain.config import PlatformConfig, PolicyConfig
from trading_platform.domain.contracts import AgentPermissionScope, OrderIntent
from trading_platform.domain.types import (
    AgentRole,
    ExecutionMode,
    OrderSide,
    OrderType,
    TimeInForce,
    compute_exact_action_hash,
)


def test_default_config_disables_execution_and_live_trading(project_root: Path) -> None:
    cfg = PlatformConfig.from_file(project_root / "config" / "platform_config.json")
    assert cfg.policy.execution_mode == ExecutionMode.DISABLED
    assert cfg.policy.allow_live_trading is False
    assert cfg.policy.allow_agent_policy_override is False
    assert cfg.policy.require_human_approval is True


def test_policy_config_forbids_live_trading_and_agent_override() -> None:
    base = dict(
        policy_version="POL-TEST-1",
        allowed_symbols=["AAPL"],
        allowed_order_types=[OrderType.LIMIT],
        allowed_time_in_force=[TimeInForce.DAY],
    )
    with pytest.raises(ValidationError):
        PolicyConfig(**base, allow_live_trading=True)
    with pytest.raises(ValidationError):
        PolicyConfig(**base, allow_agent_policy_override=True)


def test_agent_permission_scope_forbids_execution_and_approval_capabilities() -> None:
    with pytest.raises(ValidationError):
        AgentPermissionScope(
            agent_id="rogue-agent",
            role=AgentRole.PORTFOLIO_AGENT,
            allowed_tools=["get_quote"],
            can_submit_orders=True,
            max_tool_calls=5,
        )
    with pytest.raises(ValidationError):
        AgentPermissionScope(
            agent_id="rogue-agent-2",
            role=AgentRole.RESEARCH_AGENT,
            allowed_tools=["get_quote", "submit_order"],
            max_tool_calls=5,
        )


def test_exact_action_hash_changes_on_any_single_parameter_mutation() -> None:
    base_kwargs = dict(
        account_id="PAPER-ACCT-001",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=100,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("225.50"),
        time_in_force=TimeInForce.DAY,
        currency="USD",
        policy_version="POL-MATP-2026.1",
        proposal_id="PROP-001",
    )
    h1 = compute_exact_action_hash(**base_kwargs)
    h2 = compute_exact_action_hash(**{**base_kwargs, "limit_price": Decimal("225.5000")})
    assert h1 == h2  # Normalized decimal equivalence

    # Every single parameter mutation produces a distinct SHA-256 hash
    for field, mutated in [
        ("quantity", 101),
        ("limit_price", Decimal("225.51")),
        ("symbol", "MSFT"),
        ("side", OrderSide.SELL),
        ("time_in_force", TimeInForce.IOC),
        ("policy_version", "POL-MATP-2026.2"),
    ]:
        h_mut = compute_exact_action_hash(**{**base_kwargs, field: mutated})
        assert h_mut != h1, f"Mutating {field} failed to change exact_action_hash"


def test_order_intent_limit_and_market_invariants() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(
            account_id="PAPER-ACCT-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=None,
        )
    with pytest.raises(ValidationError):
        OrderIntent(
            account_id="PAPER-ACCT-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            limit_price=Decimal("225.00"),
        )
