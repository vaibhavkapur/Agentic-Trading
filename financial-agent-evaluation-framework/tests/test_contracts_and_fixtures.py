"""Contract validation, fixture integrity, and operational boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fin_eval.agents.base import OptionalLLMProviderAdapter
from fin_eval.exceptions import (
    ConfigurationError,
    ContractValidationError,
    HeldOutLeakageError,
    UnsupportedOperationError,
)
from fin_eval.runner import (
    load_dataset,
    load_fixture_store,
    load_injection_profile,
    load_model_config,
)
from fin_eval.schemas import ModelConfig
from fin_eval.tools.mock_runtime import MockToolRuntime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.mark.unit
def test_canonical_fixtures_and_configs_validate_cleanly() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    held_ds = load_dataset(FIXTURES_DIR / "gold_tasks_held_out_v1.json", allow_held_out=True)
    det_cfg = load_model_config(CONFIG_DIR / "model_deterministic.json")
    stoch_cfg = load_model_config(CONFIG_DIR / "model_stochastic.json")
    clean_faults = load_injection_profile(CONFIG_DIR / "faults_none.json")
    res_faults = load_injection_profile(CONFIG_DIR / "faults_resilience.json")

    assert len(store.evidence_records) >= 5
    assert len(dev_ds.tasks) == 8
    assert len(held_ds.tasks) == 3
    assert det_cfg.live_execution_enabled is False
    assert stoch_cfg.live_execution_enabled is False
    assert clean_faults.rules == []
    assert len(res_faults.rules) == 3


@pytest.mark.unit
def test_invalid_fixtures_fail_with_contract_validation_error() -> None:
    with pytest.raises(ContractValidationError, match="timezone-aware"):
        load_dataset(FIXTURES_DIR / "invalid" / "naive_timestamp_dataset.json")

    with pytest.raises(ContractValidationError, match="allowed and forbidden"):
        load_dataset(FIXTURES_DIR / "invalid" / "overlapping_tools_dataset.json")


@pytest.mark.unit
def test_live_execution_enabled_is_strictly_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelConfig(
            config_id="unsafe_cfg",
            model_name="unsafe-agent",
            live_execution_enabled=True,  # type: ignore[arg-type]
        )


@pytest.mark.operational
def test_held_out_dataset_leakage_guard() -> None:
    with pytest.raises(HeldOutLeakageError):
        load_dataset(FIXTURES_DIR / "gold_tasks_held_out_v1.json", allow_held_out=False)


@pytest.mark.operational
def test_missing_and_corrupt_configuration_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Missing"):
        load_model_config(tmp_path / "does_not_exist.json")

    bad_json = tmp_path / "corrupt.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Invalid JSON"):
        load_model_config(bad_json)


@pytest.mark.operational
def test_optional_llm_provider_disabled_by_default() -> None:
    store = load_fixture_store(FIXTURES_DIR / "mock_store_v1.json")
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    cfg = ModelConfig(
        config_id="llm_disabled_test",
        provider="openai_compatible",
        model_name="external-llm-stub",
        external_network_allowed=False,
    )
    runtime = MockToolRuntime(
        store=store,
        task=dev_ds.tasks[0],
        run_id="run-test",
        signing_key="test-key",
    )
    adapter = OptionalLLMProviderAdapter()
    with pytest.raises(UnsupportedOperationError, match="disabled by default"):
        adapter.run_task(
            task=dev_ds.tasks[0],
            runtime=runtime,
            config=cfg,
            run_id="run-test",
            seed=42,
        )


@pytest.mark.unit
def test_reference_oracle_fixture_matches_dev_task_spec() -> None:
    oracle = json.loads((FIXTURES_DIR / "reference_oracle_v1.json").read_text(encoding="utf-8"))
    dev_ds = load_dataset(FIXTURES_DIR / "gold_tasks_dev_v1.json")
    task = next(t for t in dev_ds.tasks if t.task_id == oracle["task_id"])

    rev = oracle["inputs"]["revenue_usd_millions"]
    op_inc = oracle["inputs"]["operating_income_usd_millions"]
    hand_margin = (op_inc / rev) * 100.0
    assert hand_margin == pytest.approx(task.expected_numeric[0].value, abs=1e-9)
