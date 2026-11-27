"""Unit tests for IndependentRiskService and SHA-256 hash-chained audit trail."""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import MutableClock

from trading_platform.domain.types import RiskStatus, RunStatus
from trading_platform.service import TradingPlatform


def test_risk_rejects_oversized_order_notional(platform: TradingPlatform) -> None:
    # 1000 shares of AAPL (~$225k) exceeds max_order_notional_usd ($100k)
    outcome = platform.run_cycle(symbol="AAPL", override_quantity=1000)
    assert outcome.run.status == RunStatus.BLOCKED_RISK
    assert outcome.risk_assessment is not None
    assert outcome.risk_assessment.status == RiskStatus.REJECTED
    failed_codes = {c.code for c in outcome.risk_assessment.failed_checks}
    assert "ORDER_NOTIONAL_BREACH" in failed_codes
    assert outcome.approval_request is None


def test_risk_rejects_limit_price_outside_collar(platform: TradingPlatform) -> None:
    # AAPL mid is $225; $260 is >1500 bps away (> 250 bps collar)
    outcome = platform.run_cycle(
        symbol="AAPL",
        override_quantity=10,
        override_limit_price=Decimal("260.00"),
    )
    assert outcome.run.status == RunStatus.BLOCKED_RISK
    assert outcome.risk_assessment is not None
    failed_codes = {c.code for c in outcome.risk_assessment.failed_checks}
    assert "PRICE_DEVIATION_BREACH" in failed_codes


def test_audit_chain_detects_tampering(platform: TradingPlatform, clock: MutableClock) -> None:
    platform.run_cycle(symbol="AAPL")
    valid, count, err = platform.repository.verify_audit_chain()
    assert valid is True
    assert count >= 5
    assert err is None

    # Tamper directly with SQLite row to prove hash chain catches modification
    platform.repository._conn.execute(
        "UPDATE audit_log SET outcome = 'TAMPERED' WHERE seq = 1"
    )
    platform.repository._conn.commit()
    valid_after, _, err_after = platform.repository.verify_audit_chain()
    assert valid_after is False
    assert err_after is not None and "Hash mismatch" in err_after
