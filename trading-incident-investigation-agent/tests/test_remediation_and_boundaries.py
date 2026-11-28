"""M4 tests: ambiguous root cause, unauthorized actions, explicit approval, recovery, and CLI diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trading_incident_agent import (
    AmbiguousRootCauseError,
    ApprovalMismatchError,
    ApprovalRequiredError,
    ConfigurationError,
    ForbiddenActionError,
    OperatorApproval,
    RemediationProposal,
    RemediationStatus,
    SimulatedTradingEnvironment,
    TradingIncidentAgent,
    VerdictStatus,
    load_config,
    load_incident_bundle,
)
from trading_incident_agent.cli import main as cli_main
from trading_incident_agent.models import ActionRiskLevel


def _make_approval(
    *,
    incident_id: str,
    proposal: RemediationProposal,
    role: str = "oncall_sre",
    digest: str | None = None,
    expires_offset_minutes: int = 10,
    acknowledge_ambiguity: bool = False,
) -> tuple[OperatorApproval, datetime]:
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    approval = OperatorApproval(
        approval_id="APR-TEST-001",
        incident_id=incident_id,
        remediation_id=proposal.remediation_id,
        plan_digest=digest if digest is not None else proposal.plan_digest,
        approver_id="operator_alice",
        approver_role=role,
        approved_at_utc=now,
        expires_at_utc=now + timedelta(minutes=expires_offset_minutes),
        rationale="Reviewed cited evidence and explicitly approved bounded simulation action.",
        acknowledge_ambiguity=acknowledge_ambiguity,
    )
    return approval, now


def test_ambiguous_root_cause_surfaces_uncertainty_and_gates_remediation(
    fixtures_dir: Path, agent: TradingIncidentAgent
) -> None:
    bundle = load_incident_bundle(fixtures_dir / "inc_ambiguous_004.json")
    report = agent.investigate(bundle)

    assert report.verdict_status == VerdictStatus.AMBIGUOUS
    assert report.primary_root_cause is None
    assert len(report.hypotheses) == 2
    competing = {h.failure_mode for h in report.hypotheses}
    assert competing == {"internal_oms_gc_pause", "exchange_venue_throttling"}
    assert any("ambiguous root cause" in n.lower() for n in report.uncertainty_notes)
    assert all(p.blocked_reason is not None for p in report.proposed_remediations)

    # Attempting remediation with approval but WITHOUT acknowledge_ambiguity must fail
    prop = report.proposed_remediations[0]
    approval, now = _make_approval(
        incident_id=report.incident_id, proposal=prop, acknowledge_ambiguity=False
    )
    env = SimulatedTradingEnvironment(seed=42)
    with pytest.raises(AmbiguousRootCauseError):
        agent.execute_remediation(
            report=report, proposal=prop, approval=approval, environment=env, now_utc=now
        )
    assert env.mutation_count == 0

    # With explicit acknowledge_ambiguity=True, operator can run bounded simulated remediation
    ack_approval, now = _make_approval(
        incident_id=report.incident_id, proposal=prop, acknowledge_ambiguity=True
    )
    receipt = agent.execute_remediation(
        report=report, proposal=prop, approval=ack_approval, environment=env, now_utc=now
    )
    assert receipt.status == RemediationStatus.EXECUTED_RECOVERED
    assert env.mutation_count == 1


def test_unauthorized_actions_are_blocked_without_state_mutation(
    fixtures_dir: Path, agent: TradingIncidentAgent
) -> None:
    bundle = load_incident_bundle(fixtures_dir / "inc_ref_001_gateway_pool.json")
    report = agent.investigate(bundle)
    prop = report.proposed_remediations[0]
    env = SimulatedTradingEnvironment(seed=42)

    # 1. Missing approval
    with pytest.raises(ApprovalRequiredError):
        agent.execute_remediation(report=report, proposal=prop, approval=None, environment=env)
    assert env.mutation_count == 0

    # 2. Unauthorized actor role
    bad_role, now = _make_approval(
        incident_id=report.incident_id, proposal=prop, role="read_only_intern"
    )
    with pytest.raises(ApprovalMismatchError):
        agent.execute_remediation(
            report=report, proposal=prop, approval=bad_role, environment=env, now_utc=now
        )
    assert env.mutation_count == 0

    # 3. Tampered / mismatched plan digest
    bad_digest, now = _make_approval(
        incident_id=report.incident_id, proposal=prop, digest="deadbeef" * 8
    )
    with pytest.raises(ApprovalMismatchError):
        agent.execute_remediation(
            report=report, proposal=prop, approval=bad_digest, environment=env, now_utc=now
        )
    assert env.mutation_count == 0

    # 4. Expired approval
    expired, now = _make_approval(
        incident_id=report.incident_id, proposal=prop, expires_offset_minutes=-5
    )
    with pytest.raises(ApprovalMismatchError):
        agent.execute_remediation(
            report=report, proposal=prop, approval=expired, environment=env, now_utc=now
        )
    assert env.mutation_count == 0

    # 5. Forbidden action (blocked even before approval check)
    forbidden_prop = RemediationProposal(
        remediation_id="REM-BAD-01",
        incident_id=report.incident_id,
        action_id="disable_risk_limits",
        target_service="risk-engine",
        risk_level=ActionRiskLevel.FORBIDDEN,
        parameters={},
        rationale="Forbidden action test",
        plan_digest="a" * 64,
    )
    with pytest.raises(ForbiddenActionError):
        agent.execute_remediation(
            report=report, proposal=forbidden_prop, approval=None, environment=env
        )
    assert env.mutation_count == 0


def test_approved_simulated_remediation_verifies_recovery_and_detects_failed_recovery(
    fixtures_dir: Path, agent: TradingIncidentAgent
) -> None:
    bundle = load_incident_bundle(fixtures_dir / "inc_ref_001_gateway_pool.json")
    report = agent.investigate(bundle)
    prop = report.proposed_remediations[0]
    approval, now = _make_approval(incident_id=report.incident_id, proposal=prop)

    # Successful recovery path
    ok_env = SimulatedTradingEnvironment(seed=42, force_recovery_failure=False)
    ok_receipt = agent.execute_remediation(
        report=report, proposal=prop, approval=approval, environment=ok_env, now_utc=now
    )
    assert ok_receipt.status == RemediationStatus.EXECUTED_RECOVERED
    assert ok_receipt.executed_in_simulation is True
    assert ok_receipt.verification is not None
    assert ok_receipt.verification.verified is True
    assert ok_receipt.verification.rollback_recommended is False
    assert all(c.passed for c in ok_receipt.verification.checks)

    # Failed recovery path -> recommends rollback
    fail_env = SimulatedTradingEnvironment(seed=42, force_recovery_failure=True)
    fail_receipt = agent.execute_remediation(
        report=report, proposal=prop, approval=approval, environment=fail_env, now_utc=now
    )
    assert fail_receipt.status == RemediationStatus.EXECUTED_RECOVERY_FAILED
    assert fail_receipt.verification is not None
    assert fail_receipt.verification.verified is False
    assert fail_receipt.verification.rollback_recommended is True


def test_operational_diagnostics_missing_config_and_cli_flows(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    # Missing configuration file raises explicit ConfigurationError
    with pytest.raises(ConfigurationError) as exc_info:
        load_config(tmp_path / "does_not_exist.json")
    assert exc_info.value.error_code == "CONFIGURATION_ERROR"

    # Malformed JSON config raises ConfigurationError
    bad_cfg = tmp_path / "bad.json"
    bad_cfg.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(bad_cfg)

    # CLI investigate & evaluate work cleanly and return non-zero on invalid fixtures
    out_json = tmp_path / "report.json"
    rc_ok = cli_main(
        [
            "investigate",
            "--fixture",
            str(fixtures_dir / "inc_ref_001_gateway_pool.json"),
            "--output-json",
            str(out_json),
            "--quiet",
        ]
    )
    assert rc_ok == 0
    assert out_json.exists()

    rc_bad = cli_main(
        [
            "investigate",
            "--fixture",
            str(fixtures_dir / "invalid_schema_version.json"),
            "--quiet",
        ]
    )
    assert rc_bad == 2

    rc_eval = cli_main(
        [
            "evaluate",
            "--fixtures-dir",
            str(fixtures_dir),
            "--quiet",
        ]
    )
    assert rc_eval == 0
