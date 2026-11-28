"""Boundary tests for malicious dataset instructions and human-review promotion governance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strategy_sandbox import (
    AssetBar,
    DatasetManifest,
    ExperimentEvaluator,
    PromotionDeniedError,
    SandboxConfig,
    StrategyProposal,
    StrategySpec,
    TrialRegistry,
    scan_dataset_safety,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_malicious_instructions_in_dataset_rejected_before_execution() -> None:
    malicious_ds = DatasetManifest.model_validate(_load_fixture("malicious_dataset.json"))
    spec = StrategySpec.model_validate(_load_fixture("reference_spec.json"))
    proposal = StrategyProposal.model_validate(_load_fixture("reference_proposal.json"))

    evaluator = ExperimentEvaluator(config=SandboxConfig())
    trial = evaluator.evaluate(proposal=proposal, spec=spec, dataset=malicious_ds)

    assert trial.status == "FAILED_DATA_SAFETY"
    assert trial.telemetry["counters"]["sandbox_invocations"] == 0
    ds_chk = next(c for c in trial.checks if c.name == "dataset_safety")
    assert not ds_chk.passed
    assert ds_chk.code == "MALICIOUS_INSTRUCTIONS_DETECTED"
    assert ds_chk.details["finding_count"] >= 2


def test_bidi_unicode_control_char_in_dataset_rejected() -> None:
    ds = DatasetManifest(
        dataset_id="bidi-attack-v1",
        version="1.0.0",
        symbols=["SYNTH_A"],
        bars=[
            AssetBar(
                timestamp="2026-01-02T16:00:00Z",  # type: ignore[arg-type]
                symbol="SYNTH_A",
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1000.0,
                note="normal text \u202e hidden override",
            ),
            AssetBar(
                timestamp="2026-01-03T16:00:00Z",  # type: ignore[arg-type]
                symbol="SYNTH_A",
                open=100.0,
                high=102.0,
                low=99.0,
                close=101.0,
                volume=1000.0,
            ),
        ],
    )
    res = scan_dataset_safety(ds)
    assert not res.passed
    assert res.code == "MALICIOUS_INSTRUCTIONS_DETECTED"


def test_promotion_governance_blocks_unreviewed_failed_and_tampered_trials(tmp_path: Path) -> None:
    dataset = DatasetManifest.model_validate(_load_fixture("reference_dataset.json"))
    spec = StrategySpec.model_validate(_load_fixture("reference_spec.json"))
    proposal = StrategyProposal.model_validate(_load_fixture("reference_proposal.json"))
    evaluator = ExperimentEvaluator(config=SandboxConfig())
    registry = TrialRegistry(tmp_path / "registry")

    # 1. Passing trial cannot be promoted without human review
    passing_trial = evaluator.evaluate(proposal=proposal, spec=spec, dataset=dataset)
    assert passing_trial.status == "PASSED"
    registry.record_trial(passing_trial)

    with pytest.raises(PromotionDeniedError, match="No matching human APPROVE"):
        registry.promote_trial(passing_trial.trial_id)

    # 2. REJECT review does not allow promotion
    registry.record_human_review(
        review_id="rev-001",
        trial_id=passing_trial.trial_id,
        reviewer="risk-officer-a",
        decision="REJECT",
        notes="Need longer backtest horizon.",
    )
    with pytest.raises(PromotionDeniedError):
        registry.promote_trial(passing_trial.trial_id)

    # 3. Hash-mismatched APPROVE review does not allow promotion
    registry.record_human_review(
        review_id="rev-002-mismatch",
        trial_id=passing_trial.trial_id,
        reviewer="risk-officer-a",
        decision="APPROVE",
        code_sha256="f" * 64,
        notes="Stale review for different code artifact.",
    )
    with pytest.raises(PromotionDeniedError):
        registry.promote_trial(passing_trial.trial_id)

    # 4. Matching APPROVE review succeeds
    registry.record_human_review(
        review_id="rev-003-ok",
        trial_id=passing_trial.trial_id,
        reviewer="quant-reviewer-b",
        decision="APPROVE",
        notes="Verified hashes, accounting, and leakage results.",
    )
    decision = registry.promote_trial(passing_trial.trial_id, review_id="rev-003-ok")
    assert decision.promoted is True
    assert decision.stage == "PAPER_STAGING_APPROVED"
    assert decision.code_sha256 == passing_trial.code_sha256
    assert decision.output_sha256 == passing_trial.output_sha256

    # 5. Replay verification reproduces identical output hash
    replay_chk = registry.replay_trial(
        trial_id=passing_trial.trial_id,
        proposal=proposal,
        spec=spec,
        dataset=dataset,
        evaluator=evaluator,
    )
    assert replay_chk.passed

    # 6. Tampering with stored trial artifact is caught and blocks promotion
    artifact_file = registry.trials_dir / f"{passing_trial.trial_id}.json"
    tampered = json.loads(artifact_file.read_text(encoding="utf-8"))
    tampered["accounting"]["final_equity"] = 999999.99
    artifact_file.write_text(json.dumps(tampered), encoding="utf-8")

    integrity = registry.verify_trial_integrity(passing_trial.trial_id)
    assert not integrity.passed
    assert integrity.code == "ARTIFACT_HASH_MISMATCH"
    with pytest.raises(PromotionDeniedError, match="integrity check"):
        registry.promote_trial(passing_trial.trial_id)

    # 7. Failed trial cannot be promoted even with matching human APPROVE
    bad_prop = StrategyProposal(
        proposal_id="prop-bad-import",
        spec_id=spec.spec_id,
        code="import os\ndef on_bar(ctx):\n    return []\n",
    )
    failed_trial = evaluator.evaluate(proposal=bad_prop, spec=spec, dataset=dataset)
    assert failed_trial.status == "FAILED_STATIC_POLICY"
    registry.record_trial(failed_trial)
    registry.record_human_review(
        review_id="rev-004-override",
        trial_id=failed_trial.trial_id,
        reviewer="reviewer-attempt",
        decision="APPROVE",
        notes="Attempted override of failed gate.",
    )
    with pytest.raises(PromotionDeniedError, match="unvalidated code cannot be promoted"):
        registry.promote_trial(failed_trial.trial_id)
