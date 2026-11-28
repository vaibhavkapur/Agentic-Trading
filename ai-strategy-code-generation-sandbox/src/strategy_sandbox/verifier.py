"""End-to-end experiment verification orchestrator.

Combines dataset safety screening, static AST policy verification, isolated
sandbox execution, future-data leakage perturbation testing, determinism
verification, paper accounting invariant checks, and reference oracle comparison.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contracts import (
    AccountingSummary,
    AssetBar,
    CheckResult,
    DatasetManifest,
    EquityPoint,
    ExperimentBudget,
    FillRecord,
    OrderIntent,
    RejectedOrderRecord,
    SandboxConfig,
    StrategyProposal,
    StrategySpec,
    TrialRecord,
)
from .data_sanitizer import scan_dataset_safety
from .errors import ConfigurationError, ContractValidationError
from .hashing import canonical_json, runtime_environment_snapshot, sha256_object
from .paper_engine import group_bars_by_timestamp, verify_accounting_invariants
from .sandbox_runner import DockerSandboxRunner, SandboxRunnerProtocol, SubprocessSandboxRunner
from .static_analyzer import analyze_strategy_code


def load_sandbox_config(path: Path) -> SandboxConfig:
    """Load and validate a SandboxConfig JSON file with explicit error reporting."""
    if not path.exists():
        raise ConfigurationError(
            f"Configuration file not found: {path}",
            details={"path": str(path)},
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Failed to parse configuration file '{path}': {exc}",
            details={"path": str(path)},
        ) from exc
    try:
        return SandboxConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Invalid SandboxConfig in '{path}': {exc.errors()[0]['msg']}",
            details={"path": str(path), "errors": exc.errors()},
        ) from exc


def make_prefix_dataset(dataset: DatasetManifest, checkpoint_step: int) -> DatasetManifest:
    """Return a valid DatasetManifest truncated to chronological steps 0..checkpoint_step."""
    steps = group_bars_by_timestamp(dataset)
    selected_steps = steps[: checkpoint_step + 1]
    bars: list[AssetBar] = []
    for _, bar_map in selected_steps:
        for sym in sorted(bar_map):
            bars.append(bar_map[sym])
    present_symbols = sorted({b.symbol for b in bars})
    return DatasetManifest(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        schema_version=dataset.schema_version,
        provenance=dataset.provenance,
        symbols=present_symbols,
        bars=bars,
        description=dataset.description,
    )


def make_future_perturbed_dataset(
    dataset: DatasetManifest,
    checkpoint_step: int,
    shock_multiplier: float = 2.5,
) -> DatasetManifest:
    """Return a valid DatasetManifest with all bars strictly AFTER checkpoint_step shocked."""
    steps = group_bars_by_timestamp(dataset)
    bars: list[AssetBar] = []
    for step_idx, (_, bar_map) in enumerate(steps):
        for sym in sorted(bar_map):
            b = bar_map[sym]
            if step_idx > checkpoint_step:
                bars.append(
                    AssetBar(
                        timestamp=b.timestamp,
                        symbol=b.symbol,
                        open=round(b.open * shock_multiplier, 6),
                        high=round(b.high * shock_multiplier, 6),
                        low=round(b.low * shock_multiplier, 6),
                        close=round(b.close * shock_multiplier, 6),
                        volume=b.volume * 1.75,
                        note=b.note,
                    )
                )
            else:
                bars.append(b)
    return DatasetManifest(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        schema_version=dataset.schema_version,
        provenance=dataset.provenance,
        symbols=list(dataset.symbols),
        bars=bars,
        description=dataset.description,
    )


def compute_trial_output_hash(
    *,
    status: str,
    checks: list[CheckResult],
    accounting: AccountingSummary | None,
    fills: list[FillRecord],
    rejected_orders: list[RejectedOrderRecord],
    equity_curve: list[EquityPoint],
) -> str:
    """Compute stable logical output hash independent of wall-clock durations."""
    logical_checks = [
        {"name": c.name, "passed": c.passed, "code": c.code}
        for c in checks
    ]
    payload = {
        "status": status,
        "checks": logical_checks,
        "accounting": accounting.model_dump(mode="json") if accounting is not None else None,
        "fills": [f.model_dump(mode="json") for f in fills],
        "rejected_orders": [r.model_dump(mode="json") for r in rejected_orders],
        "equity_curve": [e.model_dump(mode="json") for e in equity_curve],
    }
    return sha256_object(payload)


def _orders_digest(orders_by_step: list[list[OrderIntent]]) -> str:
    return sha256_object(
        [[o.model_dump(mode="json") for o in step_orders] for step_orders in orders_by_step]
    )


class ExperimentEvaluator:
    """Orchestrates full sandbox evaluation and emits immutable TrialRecords."""

    def __init__(
        self,
        config: SandboxConfig | None = None,
        runner: SandboxRunnerProtocol | None = None,
    ) -> None:
        self.config = config or SandboxConfig()
        if runner is not None:
            self.runner: SandboxRunnerProtocol = runner
        elif self.config.sandbox_backend == "docker_rootless":
            self.runner = DockerSandboxRunner()
        else:
            self.runner = SubprocessSandboxRunner()

    def evaluate(
        self,
        *,
        proposal: StrategyProposal,
        spec: StrategySpec,
        dataset: DatasetManifest,
        budget: ExperimentBudget | None = None,
        reference_expected: dict[str, Any] | None = None,
        skip_static_policy: bool = False,
    ) -> TrialRecord:
        """Run all validation, security, leakage, determinism, and accounting gates."""
        eff_budget = budget or self.config.default_budget
        eval_start = time.monotonic()
        logs: list[dict[str, Any]] = []
        counters: dict[str, int] = {
            "sandbox_invocations": 0,
            "checks_run": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "leakage_probes": 0,
            "determinism_replays": 0,
        }

        if proposal.spec_id != spec.spec_id:
            raise ContractValidationError(
                f"Proposal spec_id '{proposal.spec_id}' does not match StrategySpec '{spec.spec_id}'.",
                details={"proposal_spec_id": proposal.spec_id, "spec_id": spec.spec_id},
            )

        missing_symbols = set(spec.target_symbols) - set(dataset.symbols)
        if missing_symbols:
            raise ContractValidationError(
                f"Dataset '{dataset.dataset_id}' missing required target_symbols: {sorted(missing_symbols)}.",
                details={"missing_symbols": sorted(missing_symbols)},
            )

        assert proposal.code_sha256 is not None
        assert dataset.sha256 is not None

        input_bundle_sha256 = sha256_object(
            {
                "config_version": self.config.config_version,
                "spec": spec.model_dump(mode="json"),
                "dataset_id": dataset.dataset_id,
                "dataset_version": dataset.version,
                "dataset_sha256": dataset.sha256,
                "proposal_id": proposal.proposal_id,
                "code_sha256": proposal.code_sha256,
                "budget": eff_budget.model_dump(mode="json"),
            }
        )

        checks: list[CheckResult] = []

        def _record_check(chk: CheckResult) -> None:
            checks.append(chk)
            counters["checks_run"] += 1
            if chk.passed:
                counters["checks_passed"] += 1
            else:
                counters["checks_failed"] += 1
            logs.append(
                {
                    "event": "check_completed",
                    "check": chk.name,
                    "passed": chk.passed,
                    "code": chk.code,
                    "message": chk.message,
                }
            )

        # Gate 1: Dataset safety & untrusted-text screening
        ds_check = scan_dataset_safety(dataset)
        _record_check(ds_check)
        if not ds_check.passed:
            return self._finalize_record(
                proposal=proposal,
                spec=spec,
                dataset=dataset,
                input_bundle_sha256=input_bundle_sha256,
                status="FAILED_DATA_SAFETY",
                checks=checks,
                accounting=None,
                fills=[],
                rejected_orders=[],
                equity_curve=[],
                counters=counters,
                logs=logs,
                eval_start=eval_start,
                extra_telemetry={},
            )

        # Gate 2: Static AST security policy
        if not skip_static_policy:
            static_check = analyze_strategy_code(
                proposal.code,
                eff_budget,
                allowed_imports=self.config.allowed_imports,
            )
            _record_check(static_check)
            if not static_check.passed:
                return self._finalize_record(
                    proposal=proposal,
                    spec=spec,
                    dataset=dataset,
                    input_bundle_sha256=input_bundle_sha256,
                    status="FAILED_STATIC_POLICY",
                    checks=checks,
                    accounting=None,
                    fills=[],
                    rejected_orders=[],
                    equity_curve=[],
                    counters=counters,
                    logs=logs,
                    eval_start=eval_start,
                    extra_telemetry={},
                )

        # Gate 3: Sandboxed primary execution
        counters["sandbox_invocations"] += 1
        exec_res, engine = self.runner.run(
            code=proposal.code,
            dataset=dataset,
            spec=spec,
            budget=eff_budget,
            allowed_imports=self.config.allowed_imports,
        )
        exec_check = CheckResult(
            name="sandbox_execution",
            passed=exec_res.succeeded,
            code="OK" if exec_res.succeeded else (exec_res.error_code or "SANDBOX_EXECUTION_ERROR"),
            message=(
                f"Sandboxed execution succeeded in {exec_res.wall_time_sec:.3f}s ({exec_res.steps_executed} steps)."
                if exec_res.succeeded
                else (exec_res.error_message or "Sandboxed execution failed.")
            ),
            details={
                "wall_time_sec": exec_res.wall_time_sec,
                "timed_out": exec_res.timed_out,
                "exit_code": exec_res.exit_code,
                "peak_traced_memory_bytes": exec_res.peak_traced_memory_bytes,
                "output_bytes": exec_res.output_bytes,
                "steps_executed": exec_res.steps_executed,
                "isolation_capabilities": exec_res.isolation_capabilities,
            },
        )
        _record_check(exec_check)

        if not exec_res.succeeded:
            return self._finalize_record(
                proposal=proposal,
                spec=spec,
                dataset=dataset,
                input_bundle_sha256=input_bundle_sha256,
                status="FAILED_SANDBOX",
                checks=checks,
                accounting=None,
                fills=[],
                rejected_orders=[],
                equity_curve=[],
                counters=counters,
                logs=logs,
                eval_start=eval_start,
                extra_telemetry={"primary_exec": exec_res.model_dump(mode="json")},
            )

        summary = engine.summarize()
        baseline_orders = exec_res.orders_by_step
        baseline_fills = engine.fills
        baseline_rejected = engine.rejected_orders
        baseline_curve = engine.equity_curve

        # Gate 4: Accounting & risk invariants
        acct_check = verify_accounting_invariants(
            summary,
            baseline_curve,
            spec,
            tolerance=self.config.verification.accounting_tolerance,
        )
        _record_check(acct_check)

        # Gate 5: Determinism test (must verify determinism before perturbation leakage checks)
        det_check = self._verify_determinism(
            proposal=proposal,
            spec=spec,
            dataset=dataset,
            budget=eff_budget,
            baseline_orders=baseline_orders,
            baseline_summary=summary,
            baseline_curve=baseline_curve,
            counters=counters,
        )
        _record_check(det_check)

        # Gate 6: Future-data leakage test (future shock + prefix truncation invariance)
        leakage_check = self._verify_no_future_leakage(
            proposal=proposal,
            spec=spec,
            dataset=dataset,
            budget=eff_budget,
            baseline_orders=baseline_orders,
            counters=counters,
        )
        _record_check(leakage_check)

        # Gate 7 (optional): Reference oracle baseline comparison
        ref_check: CheckResult | None = None
        if reference_expected is not None:
            ref_check = self._verify_reference_oracle(summary, reference_expected)
            _record_check(ref_check)

        # Determine final status with explicit priority
        status: Any = "PASSED"
        if not det_check.passed:
            status = "FAILED_DETERMINISM"
        elif not leakage_check.passed:
            status = "FAILED_LEAKAGE"
        elif not acct_check.passed:
            status = "FAILED_ACCOUNTING"
        elif ref_check is not None and not ref_check.passed:
            status = "FAILED_REFERENCE_ORACLE"

        return self._finalize_record(
            proposal=proposal,
            spec=spec,
            dataset=dataset,
            input_bundle_sha256=input_bundle_sha256,
            status=status,
            checks=checks,
            accounting=summary,
            fills=baseline_fills,
            rejected_orders=baseline_rejected,
            equity_curve=baseline_curve,
            counters=counters,
            logs=logs,
            eval_start=eval_start,
            extra_telemetry={
                "primary_wall_time_sec": exec_res.wall_time_sec,
                "peak_traced_memory_bytes": exec_res.peak_traced_memory_bytes,
                "output_bytes": exec_res.output_bytes,
                "isolation_capabilities": exec_res.isolation_capabilities,
            },
        )

    def _verify_no_future_leakage(
        self,
        *,
        proposal: StrategyProposal,
        spec: StrategySpec,
        dataset: DatasetManifest,
        budget: ExperimentBudget,
        baseline_orders: list[list[OrderIntent]],
        counters: dict[str, int],
    ) -> CheckResult:
        total_steps = len(group_bars_by_timestamp(dataset))
        if total_steps < 3:
            return CheckResult(
                name="future_data_leakage",
                passed=True,
                code="SKIPPED_SHORT_SERIES",
                message="Dataset has fewer than 3 steps; prefix/future-shock checkpoints not applicable.",
                details={"total_steps": total_steps},
            )

        checkpoints: list[int] = []
        for frac in self.config.verification.leakage_checkpoint_fractions:
            cp = max(1, min(total_steps - 2, int(total_steps * frac)))
            if cp not in checkpoints:
                checkpoints.append(cp)

        probe_results: list[dict[str, Any]] = []
        for cp in checkpoints:
            baseline_prefix_digest = _orders_digest(baseline_orders[: cp + 1])

            # Probe A: Shock all bars strictly after checkpoint cp
            shocked_ds = make_future_perturbed_dataset(
                dataset,
                checkpoint_step=cp,
                shock_multiplier=self.config.verification.leakage_future_shock_multiplier,
            )
            counters["sandbox_invocations"] += 1
            counters["leakage_probes"] += 1
            shocked_res, _ = self.runner.run(
                code=proposal.code,
                dataset=shocked_ds,
                spec=spec,
                budget=budget,
                allowed_imports=self.config.allowed_imports,
            )
            if not shocked_res.succeeded:
                return CheckResult(
                    name="future_data_leakage",
                    passed=False,
                    code="LEAKAGE_PROBE_EXEC_FAILED",
                    message=f"Future-shock leakage probe failed at checkpoint {cp}: {shocked_res.error_message}",
                    details={"checkpoint": cp, "probe": "future_shock", "error": shocked_res.error_code},
                )
            shocked_prefix_digest = _orders_digest(shocked_res.orders_by_step[: cp + 1])
            if shocked_prefix_digest != baseline_prefix_digest:
                return CheckResult(
                    name="future_data_leakage",
                    passed=False,
                    code="FUTURE_DATA_LEAKAGE",
                    message=f"Future-data leakage detected: orders in steps 0..{cp} changed when future bars >{cp} were perturbed.",
                    details={
                        "checkpoint": cp,
                        "probe": "future_shock",
                        "baseline_prefix_digest": baseline_prefix_digest,
                        "shocked_prefix_digest": shocked_prefix_digest,
                    },
                )

            # Probe B: Truncate dataset strictly to prefix 0..cp
            prefix_ds = make_prefix_dataset(dataset, checkpoint_step=cp)
            counters["sandbox_invocations"] += 1
            counters["leakage_probes"] += 1
            prefix_res, _ = self.runner.run(
                code=proposal.code,
                dataset=prefix_ds,
                spec=spec,
                budget=budget,
                allowed_imports=self.config.allowed_imports,
            )
            if not prefix_res.succeeded:
                return CheckResult(
                    name="future_data_leakage",
                    passed=False,
                    code="LEAKAGE_PROBE_EXEC_FAILED",
                    message=f"Prefix-truncation leakage probe failed at checkpoint {cp}: {prefix_res.error_message}",
                    details={"checkpoint": cp, "probe": "prefix_truncation", "error": prefix_res.error_code},
                )
            truncated_digest = _orders_digest(prefix_res.orders_by_step)
            if truncated_digest != baseline_prefix_digest:
                return CheckResult(
                    name="future_data_leakage",
                    passed=False,
                    code="FUTURE_DATA_LEAKAGE",
                    message=f"Future-data leakage detected: orders in steps 0..{cp} differed under prefix truncation.",
                    details={
                        "checkpoint": cp,
                        "probe": "prefix_truncation",
                        "baseline_prefix_digest": baseline_prefix_digest,
                        "truncated_digest": truncated_digest,
                    },
                )

            probe_results.append(
                {
                    "checkpoint": cp,
                    "prefix_digest": baseline_prefix_digest,
                    "future_shock_match": True,
                    "prefix_truncation_match": True,
                }
            )

        return CheckResult(
            name="future_data_leakage",
            passed=True,
            code="OK",
            message=f"No future-data leakage detected across {len(checkpoints)} checkpoint(s) (future-shock + prefix-truncation invariant).",
            details={"checkpoints_tested": probe_results},
        )

    def _verify_determinism(
        self,
        *,
        proposal: StrategyProposal,
        spec: StrategySpec,
        dataset: DatasetManifest,
        budget: ExperimentBudget,
        baseline_orders: list[list[OrderIntent]],
        baseline_summary: AccountingSummary,
        baseline_curve: list[EquityPoint],
        counters: dict[str, int],
    ) -> CheckResult:
        baseline_digest = sha256_object(
            {
                "orders": [[o.model_dump(mode="json") for o in s] for s in baseline_orders],
                "summary": baseline_summary.model_dump(mode="json"),
                "equity_curve": [e.model_dump(mode="json") for e in baseline_curve],
            }
        )
        repeats = max(1, self.config.verification.determinism_repeats - 1)
        for rep in range(1, repeats + 1):
            counters["sandbox_invocations"] += 1
            counters["determinism_replays"] += 1
            replay_res, replay_engine = self.runner.run(
                code=proposal.code,
                dataset=dataset,
                spec=spec,
                budget=budget,
                allowed_imports=self.config.allowed_imports,
            )
            if not replay_res.succeeded:
                return CheckResult(
                    name="determinism",
                    passed=False,
                    code="DETERMINISM_REPLAY_FAILED",
                    message=f"Replay {rep} failed: {replay_res.error_message}",
                    details={"replay": rep, "error_code": replay_res.error_code},
                )
            replay_summary = replay_engine.summarize()
            replay_digest = sha256_object(
                {
                    "orders": [[o.model_dump(mode="json") for o in s] for s in replay_res.orders_by_step],
                    "summary": replay_summary.model_dump(mode="json"),
                    "equity_curve": [e.model_dump(mode="json") for e in replay_engine.equity_curve],
                }
            )
            if replay_digest != baseline_digest:
                return CheckResult(
                    name="determinism",
                    passed=False,
                    code="NONDETERMINISTIC_BEHAVIOR",
                    message=f"Replay {rep} produced different logical outputs under identical inputs and seed={spec.seed}.",
                    details={
                        "replay": rep,
                        "seed": spec.seed,
                        "baseline_digest": baseline_digest,
                        "replay_digest": replay_digest,
                    },
                )

        return CheckResult(
            name="determinism",
            passed=True,
            code="OK",
            message=f"Deterministic across {repeats + 1} identical runs (seed={spec.seed}, digest={baseline_digest[:12]}).",
            details={"runs": repeats + 1, "seed": spec.seed, "logical_digest": baseline_digest},
        )

    def _verify_reference_oracle(
        self,
        summary: AccountingSummary,
        expected: dict[str, Any],
    ) -> CheckResult:
        tol = self.config.verification.reference_equity_tolerance
        deviations: dict[str, Any] = {}
        observed = summary.model_dump(mode="json")

        for key, exp_val in expected.items():
            if key not in observed:
                deviations[key] = {"expected": exp_val, "observed": None, "reason": "missing_field"}
                continue
            obs_val = observed[key]
            if isinstance(exp_val, (int, float)) and not isinstance(exp_val, bool):
                diff = abs(float(obs_val) - float(exp_val))
                if diff > tol:
                    deviations[key] = {
                        "expected": exp_val,
                        "observed": obs_val,
                        "abs_diff": diff,
                        "tolerance": tol,
                    }
            elif obs_val != exp_val:
                deviations[key] = {"expected": exp_val, "observed": obs_val}

        if deviations:
            return CheckResult(
                name="reference_oracle",
                passed=False,
                code="REFERENCE_DEVIATION",
                message=f"Reference oracle mismatch on {len(deviations)} field(s): {sorted(deviations)}.",
                details={"tolerance": tol, "deviations": deviations},
            )

        return CheckResult(
            name="reference_oracle",
            passed=True,
            code="OK",
            message=f"Matched hand-calculated reference oracle across {len(expected)} metric(s) within tolerance {tol:.1e}.",
            details={"tolerance": tol, "checked_fields": sorted(expected.keys())},
        )

    def _finalize_record(
        self,
        *,
        proposal: StrategyProposal,
        spec: StrategySpec,
        dataset: DatasetManifest,
        input_bundle_sha256: str,
        status: Any,
        checks: list[CheckResult],
        accounting: AccountingSummary | None,
        fills: list[FillRecord],
        rejected_orders: list[RejectedOrderRecord],
        equity_curve: list[EquityPoint],
        counters: dict[str, int],
        logs: list[dict[str, Any]],
        eval_start: float,
        extra_telemetry: dict[str, Any],
    ) -> TrialRecord:
        assert proposal.code_sha256 is not None
        assert dataset.sha256 is not None

        output_sha256 = compute_trial_output_hash(
            status=status,
            checks=checks,
            accounting=accounting,
            fills=fills,
            rejected_orders=rejected_orders,
            equity_curve=equity_curve,
        )
        trial_id = f"trial-{input_bundle_sha256[:12]}-{output_sha256[:8]}"
        total_eval_sec = round(time.monotonic() - eval_start, 6)

        logs.append(
            {
                "event": "trial_finalized",
                "trial_id": trial_id,
                "status": status,
                "output_sha256": output_sha256,
                "total_eval_sec": total_eval_sec,
            }
        )

        return TrialRecord(
            trial_id=trial_id,
            proposal_id=proposal.proposal_id,
            spec_id=spec.spec_id,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            status=status,
            code_sha256=proposal.code_sha256,
            dataset_sha256=dataset.sha256,
            input_bundle_sha256=input_bundle_sha256,
            output_sha256=output_sha256,
            checks=checks,
            accounting=accounting,
            fills=fills,
            rejected_orders=rejected_orders,
            equity_curve=equity_curve,
            telemetry={
                "counters": counters,
                "total_eval_sec": total_eval_sec,
                **extra_telemetry,
            },
            runtime_env=runtime_environment_snapshot(self.runner.backend_name),
            structured_logs=logs,
        )
