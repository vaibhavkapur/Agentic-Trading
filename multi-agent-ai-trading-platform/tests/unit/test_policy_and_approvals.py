"""Unit tests for deterministic PolicyEngine and ExactActionApprovalService."""

from __future__ import annotations

import pytest
from tests.conftest import MutableClock

from trading_platform.domain.errors import ApprovalError, PolicyViolationError
from trading_platform.domain.types import ApprovalStatus, ExecutionMode
from trading_platform.service import TradingPlatform


def test_policy_blocks_live_mode_and_unauthorized_actors(platform: TradingPlatform) -> None:
    with pytest.raises(PolicyViolationError) as exc_live:
        platform.set_execution_mode(mode="LIVE", actor_id="ops_approver_1")
    assert exc_live.value.code == "LIVE_TRADING_FORBIDDEN"

    with pytest.raises(PolicyViolationError) as exc_auth:
        platform.set_execution_mode(mode="PAPER", actor_id="research-fundamental-v1")
    assert exc_auth.value.code == "UNAUTHORIZED_MODE_CHANGE"

    mode = platform.set_execution_mode(mode="PAPER", actor_id="ops_approver_1")
    assert mode == ExecutionMode.PAPER


def test_policy_rejects_agent_override_attempt(platform: TradingPlatform) -> None:
    with pytest.raises(PolicyViolationError) as exc_info:
        platform.policy_engine.reject_agent_override_attempt(
            agent_id="portfolio-allocator-v1",
            requested_change="raise max_order_notional_usd to 10M",
        )
    assert exc_info.value.code == "AGENT_POLICY_OVERRIDE_FORBIDDEN"


def test_approval_requires_authorized_human_and_exact_hash_and_ttl(
    platform: TradingPlatform,
    clock: MutableClock,
) -> None:
    outcome = platform.run_cycle(symbol="AAPL", approval_ttl_seconds=60)
    assert outcome.approval_request is not None
    req = outcome.approval_request

    # Unauthorized actor (e.g., agent) cannot approve
    with pytest.raises(ApprovalError) as exc_unauth:
        platform.decide_approval(
            approval_id=req.approval_id,
            actor_id="portfolio-allocator-v1",
            approve=True,
            expected_action_hash=req.exact_action_hash,
            reason="Self approval attempt",
        )
    assert exc_unauth.value.code == "APPROVER_NOT_AUTHORIZED"

    # Wrong hash fails
    with pytest.raises(ApprovalError) as exc_hash:
        platform.decide_approval(
            approval_id=req.approval_id,
            actor_id="ops_approver_1",
            approve=True,
            expected_action_hash="f" * 64,
            reason="Wrong hash",
        )
    assert exc_hash.value.code == "APPROVAL_HASH_MISMATCH"

    # Advance clock past TTL -> expired
    clock.advance(61)
    with pytest.raises(ApprovalError) as exc_exp:
        platform.decide_approval(
            approval_id=req.approval_id,
            actor_id="ops_approver_1",
            approve=True,
            expected_action_hash=req.exact_action_hash,
            reason="Late approval",
        )
    assert exc_exp.value.code == "APPROVAL_EXPIRED"
    persisted = platform.repository.get_approval(req.approval_id)
    assert persisted is not None and persisted.status == ApprovalStatus.EXPIRED
