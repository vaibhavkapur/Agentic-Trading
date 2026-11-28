"""Operational review tests: missing config, unsupported backends, mismatched contracts, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strategy_sandbox import (
    ConfigurationError,
    ContractValidationError,
    DatasetManifest,
    DockerSandboxRunner,
    ExperimentEvaluator,
    SandboxConfig,
    StrategyProposal,
    StrategySpec,
    load_sandbox_config,
)
from strategy_sandbox.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"
CONFIG_PATH = ROOT / "config" / "default_sandbox_config.json"


def test_missing_and_invalid_config_raise_explicit_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_sandbox_config(tmp_path / "does_not_exist.json")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-valid-json", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Failed to parse"):
        load_sandbox_config(bad_json)

    bad_schema = tmp_path / "bad_schema.json"
    bad_schema.write_text(json.dumps({"sandbox_backend": "unknown_backend"}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Invalid SandboxConfig"):
        load_sandbox_config(bad_schema)


def test_mismatched_spec_and_missing_dataset_symbol_fail_explicitly() -> None:
    dataset = DatasetManifest.model_validate(
        json.loads((FIXTURES / "reference_dataset.json").read_text(encoding="utf-8"))
    )
    spec = StrategySpec.model_validate(
        json.loads((FIXTURES / "reference_spec.json").read_text(encoding="utf-8"))
    )
    wrong_prop = StrategyProposal(
        proposal_id="prop-wrong-spec",
        spec_id="different-spec-id",
        code="def on_bar(ctx):\n    return []\n",
    )
    evaluator = ExperimentEvaluator(config=SandboxConfig())

    with pytest.raises(ContractValidationError, match="does not match"):
        evaluator.evaluate(proposal=wrong_prop, spec=spec, dataset=dataset)

    spec_missing_sym = spec.model_copy(update={"target_symbols": ["SYNTH_MISSING"]})
    prop_ok_id = StrategyProposal(
        proposal_id="prop-ok",
        spec_id=spec.spec_id,
        code="def on_bar(ctx):\n    return []\n",
    )
    with pytest.raises(ContractValidationError, match="missing required target_symbols"):
        evaluator.evaluate(proposal=prop_ok_id, spec=spec_missing_sym, dataset=dataset)


def test_docker_backend_reports_unsupported_explicitly_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DockerSandboxRunner, "is_available", staticmethod(lambda: False))
    cfg = SandboxConfig(sandbox_backend="docker_rootless")
    evaluator = ExperimentEvaluator(config=cfg)

    dataset = DatasetManifest.model_validate(
        json.loads((FIXTURES / "reference_dataset.json").read_text(encoding="utf-8"))
    )
    spec = StrategySpec.model_validate(
        json.loads((FIXTURES / "reference_spec.json").read_text(encoding="utf-8"))
    )
    proposal = StrategyProposal.model_validate(
        json.loads((FIXTURES / "reference_proposal.json").read_text(encoding="utf-8"))
    )
    trial = evaluator.evaluate(proposal=proposal, spec=spec, dataset=dataset)
    assert trial.status == "FAILED_SANDBOX"
    chk = next(c for c in trial.checks if c.name == "sandbox_execution")
    assert chk.code == "UNSUPPORTED_BACKEND"


def test_cli_end_to_end_validate_run_review_promote(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reg_dir = tmp_path / "cli_registry"

    # Missing config exits non-zero cleanly
    rc_missing = cli_main(["validate-config", "--config", str(tmp_path / "missing.json")])
    assert rc_missing == 3
    capsys.readouterr()

    # Validate valid config
    rc_cfg = cli_main(["validate-config", "--config", str(CONFIG_PATH)])
    assert rc_cfg == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    # Run reference trial
    rc_run = cli_main(
        [
            "run-trial",
            "--config",
            str(CONFIG_PATH),
            "--spec",
            str(FIXTURES / "reference_spec.json"),
            "--dataset",
            str(FIXTURES / "reference_dataset.json"),
            "--proposal",
            str(FIXTURES / "reference_proposal.json"),
            "--reference",
            str(FIXTURES / "reference_expected.json"),
            "--registry-dir",
            str(reg_dir),
        ]
    )
    assert rc_run == 0
    run_out = json.loads(capsys.readouterr().out)
    trial_id = run_out["trial_id"]
    assert run_out["status"] == "PASSED"

    # Attempt promotion before human review -> non-zero error
    rc_premature = cli_main(["promote", "--registry-dir", str(reg_dir), "--trial-id", trial_id])
    assert rc_premature == 3
    capsys.readouterr()

    # Record human review and promote
    rc_rev = cli_main(
        [
            "review",
            "--registry-dir",
            str(reg_dir),
            "--trial-id",
            trial_id,
            "--review-id",
            "cli-rev-1",
            "--reviewer",
            "qa-reviewer",
            "--decision",
            "APPROVE",
            "--notes",
            "All acceptance checks verified.",
        ]
    )
    assert rc_rev == 0
    capsys.readouterr()

    rc_prom = cli_main(["promote", "--registry-dir", str(reg_dir), "--trial-id", trial_id])
    assert rc_prom == 0
    prom_out = json.loads(capsys.readouterr().out)
    assert prom_out["promoted"] is True
    assert prom_out["stage"] == "PAPER_STAGING_APPROVED"
