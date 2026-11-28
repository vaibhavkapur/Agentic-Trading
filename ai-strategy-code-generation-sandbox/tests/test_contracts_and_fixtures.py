"""Unit tests for data contracts, fixtures, and hand-calculated reference oracle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from strategy_sandbox import (
    AssetBar,
    DatasetManifest,
    ExperimentBudget,
    ExperimentEvaluator,
    SandboxConfig,
    StrategyProposal,
    StrategySpec,
    load_sandbox_config,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"
CONFIG_PATH = ROOT / "config" / "default_sandbox_config.json"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_reference_fixtures_parse_and_hash() -> None:
    dataset = DatasetManifest.model_validate(_load_fixture("reference_dataset.json"))
    spec = StrategySpec.model_validate(_load_fixture("reference_spec.json"))
    proposal = StrategyProposal.model_validate(_load_fixture("reference_proposal.json"))

    assert dataset.sha256 is not None and len(dataset.sha256) == 64
    assert proposal.code_sha256 is not None and len(proposal.code_sha256) == 64
    assert spec.target_symbols == ["SYNTH_A"]


def test_invalid_ohlc_fixture_rejected() -> None:
    raw = _load_fixture("invalid_dataset_ohlc.json")
    with pytest.raises(ValidationError, match="high must be >= max"):
        DatasetManifest.model_validate(raw)


def test_naive_timestamp_and_non_finite_price_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AssetBar(
            timestamp="2026-01-02T16:00:00",  # type: ignore[arg-type]
            symbol="SYNTH_A",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=100.0,
        )

    with pytest.raises(ValidationError):
        AssetBar(
            timestamp="2026-01-02T16:00:00Z",  # type: ignore[arg-type]
            symbol="SYNTH_A",
            open=float("nan"),
            high=101.0,
            low=99.0,
            close=100.0,
            volume=100.0,
        )


def test_dataset_sha256_mismatch_and_unsorted_bars_rejected() -> None:
    raw = _load_fixture("reference_dataset.json")
    raw["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="sha256 mismatch"):
        DatasetManifest.model_validate(raw)

    unsorted = _load_fixture("reference_dataset.json")
    unsorted["bars"][0], unsorted["bars"][1] = unsorted["bars"][1], unsorted["bars"][0]
    with pytest.raises(ValidationError, match="globally sorted"):
        DatasetManifest.model_validate(unsorted)


def test_budget_forbids_network_and_filesystem_writes() -> None:
    with pytest.raises(ValidationError):
        ExperimentBudget(allow_network=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ExperimentBudget(allow_filesystem_write=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ExperimentBudget(allow_subprocess=True)  # type: ignore[arg-type]


def test_proposal_code_hash_mismatch_rejected() -> None:
    raw = _load_fixture("reference_proposal.json")
    raw["code_sha256"] = "a" * 64
    with pytest.raises(ValidationError, match="code_sha256 mismatch"):
        StrategyProposal.model_validate(raw)


def test_reference_strategy_matches_hand_calculated_oracle() -> None:
    cfg: SandboxConfig = load_sandbox_config(CONFIG_PATH)
    dataset = DatasetManifest.model_validate(_load_fixture("reference_dataset.json"))
    spec = StrategySpec.model_validate(_load_fixture("reference_spec.json"))
    proposal = StrategyProposal.model_validate(_load_fixture("reference_proposal.json"))
    expected = _load_fixture("reference_expected.json")

    evaluator = ExperimentEvaluator(config=cfg)
    trial = evaluator.evaluate(
        proposal=proposal,
        spec=spec,
        dataset=dataset,
        reference_expected=expected,
    )

    assert trial.status == "PASSED", [c.model_dump() for c in trial.checks if not c.passed]
    assert trial.accounting is not None
    assert abs(trial.accounting.final_equity - expected["final_equity"]) <= 1e-6
    assert abs(trial.accounting.realized_pnl - expected["realized_pnl"]) <= 1e-6
    assert abs(trial.accounting.total_commission - expected["total_commission"]) <= 1e-6
    assert trial.accounting.trade_count == expected["trade_count"]
    assert trial.accounting.max_accounting_identity_error <= 1e-9
    assert all(c.passed for c in trial.checks)
