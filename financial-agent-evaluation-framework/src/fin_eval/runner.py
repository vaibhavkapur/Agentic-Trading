"""Evaluation runner, structured logging, replay/rerun support, and report export."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError

from fin_eval import SCHEMA_VERSION, __version__
from fin_eval.agents.base import FinancialAgentAdapter
from fin_eval.agents.mock_agents import build_agent_from_config
from fin_eval.evaluator import build_evaluation_report, evaluate_task_trajectory
from fin_eval.exceptions import (
    ConfigurationError,
    ContractValidationError,
    HeldOutLeakageError,
)
from fin_eval.injection import FailureInjectionEngine
from fin_eval.schemas import (
    AgentTrajectory,
    DatasetSplit,
    EvaluationReport,
    EvidenceRecord,
    FailureInjectionProfile,
    GoldTask,
    GoldTaskDataset,
    MockFixtureStore,
    ModelConfig,
    RuntimeEnvironment,
    TaskEvaluationResult,
    ToolExecutionReceipt,
    compute_sha256,
)
from fin_eval.stats import compare_reports
from fin_eval.tools.mock_runtime import MockToolRuntime


class ReplayTaskRecord(BaseModel):
    """Saved single-task execution artifact enabling deterministic offline replay."""

    task: GoldTask
    trajectory: AgentTrajectory
    retrieved_evidence: list[EvidenceRecord]
    receipts: list[ToolExecutionReceipt]
    signing_key: str
    faults_triggered: list[str]
    extra_canaries: list[str]


class ReplayBundle(BaseModel):
    """Complete replayable artifact bundle for deterministic re-grading."""

    schema_version: str = SCHEMA_VERSION
    bundle_id: str
    dataset_id: str
    dataset_version: str
    dataset_split: DatasetSplit
    fixture_version: str
    failure_injection_profile_id: str
    model_config_snapshot: ModelConfig
    seeds: list[int]
    records: list[ReplayTaskRecord]


def capture_runtime_environment() -> RuntimeEnvironment:
    """Capture Python, OS, and key pinned dependency versions."""
    packages: dict[str, str] = {}
    for name in ("pydantic", "pydantic-core", "pytest"):
        try:
            packages[name] = pkg_version(name)
        except PackageNotFoundError:
            packages[name] = "not-installed"
    return RuntimeEnvironment(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        framework_version=__version__,
        schema_version=SCHEMA_VERSION,
        installed_packages=packages,
    )


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"Missing {label} file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {label} ({path}): {exc}") from exc


def load_dataset(path: Path, allow_held_out: bool = False) -> GoldTaskDataset:
    """Load and validate a versioned GoldTaskDataset with held-out isolation guard."""
    raw = _load_json_file(path, "gold task dataset")
    try:
        dataset = GoldTaskDataset.model_validate(raw)
    except ValidationError as exc:
        raise ContractValidationError(f"Invalid dataset contract in {path}: {exc}") from exc

    if dataset.split == DatasetSplit.HELD_OUT and not allow_held_out:
        raise HeldOutLeakageError(
            f"Refusing to load held-out dataset '{dataset.dataset_id}' without explicit "
            "allow_held_out=True (--include-held-out). Keep held-out evaluation sets separate."
        )
    return dataset


def load_fixture_store(path: Path) -> MockFixtureStore:
    """Load and validate the offline MockFixtureStore."""
    raw = _load_json_file(path, "mock fixture store")
    try:
        return MockFixtureStore.model_validate(raw)
    except ValidationError as exc:
        raise ContractValidationError(f"Invalid fixture store in {path}: {exc}") from exc


def load_model_config(path: Path) -> ModelConfig:
    """Load and validate a ModelConfig."""
    raw = _load_json_file(path, "model configuration")
    try:
        return ModelConfig.model_validate(raw)
    except ValidationError as exc:
        raise ContractValidationError(f"Invalid model config in {path}: {exc}") from exc


def load_injection_profile(path: Path | None) -> FailureInjectionProfile:
    """Load and validate a FailureInjectionProfile, or return an empty no-fault profile."""
    if path is None:
        return FailureInjectionProfile(
            profile_id="none",
            version="1.0.0",
            description="No failure injection enabled.",
            rules=[],
        )
    raw = _load_json_file(path, "failure injection profile")
    try:
        return FailureInjectionProfile.model_validate(raw)
    except ValidationError as exc:
        raise ContractValidationError(f"Invalid failure injection profile in {path}: {exc}") from exc


def load_report(path: Path) -> EvaluationReport:
    """Load a previously saved EvaluationReport for baseline comparison."""
    raw = _load_json_file(path, "baseline evaluation report")
    try:
        return EvaluationReport.model_validate(raw)
    except ValidationError as exc:
        raise ContractValidationError(f"Invalid evaluation report in {path}: {exc}") from exc


def run_evaluation(
    *,
    dataset: GoldTaskDataset,
    store: MockFixtureStore,
    model_config: ModelConfig,
    injection_profile: FailureInjectionProfile | None = None,
    agent: FinancialAgentAdapter | None = None,
    seeds: Sequence[int] | None = None,
    baseline_report: EvaluationReport | None = None,
    baseline_tolerance: float = 0.02,
    out_dir: Path | None = None,
) -> tuple[EvaluationReport, ReplayBundle, list[dict[str, Any]]]:
    """Execute an evaluation suite across one or more seeds and optionally persist artifacts."""
    profile = injection_profile or FailureInjectionProfile(
        profile_id="none",
        version="1.0.0",
        description="No failure injection enabled.",
        rules=[],
    )
    active_agent = agent or build_agent_from_config(model_config)
    run_seeds = list(seeds) if seeds else [model_config.seed]

    task_results: list[TaskEvaluationResult] = []
    replay_records: list[ReplayTaskRecord] = []
    structured_logs: list[dict[str, Any]] = []
    counters: dict[str, int] = {
        "tasks_executed": 0,
        "tasks_passed": 0,
        "tasks_failed": 0,
        "tool_calls_total": 0,
        "tool_calls_ok": 0,
        "tool_calls_error": 0,
        "tool_calls_blocked_policy": 0,
        "faults_injected": 0,
    }

    for seed in run_seeds:
        run_id = f"run-{dataset.dataset_id}-{model_config.config_id}-s{seed}"
        # Deterministic per-run signing key so replay verification is reproducible
        signing_key = compute_sha256({"run_id": run_id, "seed": seed, "config": model_config.config_id})
        injector = FailureInjectionEngine(profile=profile, seed=seed)

        for task in dataset.tasks:
            fault_start_idx = len(injector.triggered_fault_ids)
            canary_start_idx = len(injector.active_canaries)
            runtime = MockToolRuntime(
                store=store,
                task=task,
                run_id=run_id,
                signing_key=signing_key,
                max_tool_calls=model_config.max_tool_calls,
                injection_engine=injector,
            )

            trajectory = active_agent.run_task(
                task=task,
                runtime=runtime,
                config=model_config,
                run_id=run_id,
                seed=seed,
            )

            task_faults = injector.triggered_fault_ids[fault_start_idx:]
            task_canaries = injector.active_canaries[canary_start_idx:]
            retrieved = list(runtime.retrieved_evidence.values())

            result = evaluate_task_trajectory(
                task=task,
                trajectory=trajectory,
                retrieved_evidence=retrieved,
                receipts=runtime.receipts,
                signing_key=signing_key,
                model_config=model_config,
                faults_triggered=task_faults,
                extra_canaries=task_canaries,
            )

            task_results.append(result)
            replay_records.append(
                ReplayTaskRecord(
                    task=task,
                    trajectory=trajectory,
                    retrieved_evidence=retrieved,
                    receipts=list(runtime.receipts),
                    signing_key=signing_key,
                    faults_triggered=task_faults,
                    extra_canaries=task_canaries,
                )
            )

            counters["tasks_executed"] += 1
            if result.passed:
                counters["tasks_passed"] += 1
            else:
                counters["tasks_failed"] += 1
            for k in (
                "tool_calls_total",
                "tool_calls_ok",
                "tool_calls_error",
                "tool_calls_blocked_policy",
                "faults_injected",
            ):
                counters[k] += runtime.counters[k]

            structured_logs.append(
                {
                    "event": "task_evaluated",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "seed": seed,
                    "task_id": task.task_id,
                    "category": task.category.value,
                    "passed": result.passed,
                    "overall_score": result.overall_score,
                    "failure_types": [f.value for f in result.failure_types],
                    "faults_triggered": task_faults,
                    "receipt_verified": result.receipt_verified,
                    "cost_usd": result.cost_usd,
                    "latency_ms": result.latency_ms,
                }
            )

    report = build_evaluation_report(
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        dataset_split=dataset.split,
        fixture_version=store.fixture_version,
        model_config=model_config,
        failure_injection_profile_id=profile.profile_id,
        seeds=run_seeds,
        task_results=task_results,
        runtime_environment=capture_runtime_environment(),
        diagnostic_counters=counters,
    )

    if baseline_report is not None:
        comparison = compare_reports(report, baseline_report, tolerance=baseline_tolerance)
        report = report.model_copy(update={"baseline_comparison": comparison})

    bundle = ReplayBundle(
        bundle_id=f"bundle-{report.report_id}",
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        dataset_split=dataset.split,
        fixture_version=store.fixture_version,
        failure_injection_profile_id=profile.profile_id,
        model_config_snapshot=model_config,
        seeds=run_seeds,
        records=replay_records,
    )

    if out_dir is not None:
        write_evaluation_artifacts(out_dir=out_dir, report=report, bundle=bundle, logs=structured_logs)

    return report, bundle, structured_logs


def replay_evaluation(bundle: ReplayBundle) -> EvaluationReport:
    """Deterministically re-grade a saved ReplayBundle without re-running agents or tools."""
    task_results: list[TaskEvaluationResult] = []
    counters: dict[str, int] = {"tasks_replayed": 0, "tasks_passed": 0, "tasks_failed": 0}

    for rec in bundle.records:
        res = evaluate_task_trajectory(
            task=rec.task,
            trajectory=rec.trajectory,
            retrieved_evidence=rec.retrieved_evidence,
            receipts=rec.receipts,
            signing_key=rec.signing_key,
            model_config=bundle.model_config_snapshot,
            faults_triggered=rec.faults_triggered,
            extra_canaries=rec.extra_canaries,
        )
        task_results.append(res)
        counters["tasks_replayed"] += 1
        if res.passed:
            counters["tasks_passed"] += 1
        else:
            counters["tasks_failed"] += 1

    return build_evaluation_report(
        dataset_id=bundle.dataset_id,
        dataset_version=bundle.dataset_version,
        dataset_split=bundle.dataset_split,
        fixture_version=bundle.fixture_version,
        model_config=bundle.model_config_snapshot,
        failure_injection_profile_id=bundle.failure_injection_profile_id,
        seeds=bundle.seeds,
        task_results=task_results,
        runtime_environment=capture_runtime_environment(),
        diagnostic_counters=counters,
    )


def render_markdown_report(report: EvaluationReport) -> str:
    """Render a concise human-readable Markdown summary for an EvaluationReport."""
    s = report.summary
    lines = [
        f"# Evaluation Report: `{report.report_id}`",
        "",
        "## Metadata",
        f"- **Dataset:** `{report.dataset_id}` v{report.dataset_version} (`{report.dataset_split.value}`)",
        f"- **Fixture Version:** `{report.fixture_version}`",
        f"- **Model Config:** `{report.config_id}` v{report.config_version} (`{report.model_config_snapshot.model_name}`)",
        f"- **Failure Injection Profile:** `{report.failure_injection_profile_id}`",
        f"- **Seeds:** `{report.seeds}`",
        f"- **Created (UTC):** `{report.created_at_utc.isoformat()}`",
        f"- **Environment:** Python {report.runtime_environment.python_version} ({report.runtime_environment.platform})",
        "",
        "## Summary Metrics",
        "| Metric | Value | 95% Confidence Interval |",
        "|---|---|---|",
        f"| Pass Rate ({s.pass_rate.method}) | {s.pass_rate.mean:.2%} | [{s.pass_rate.lower:.2%}, {s.pass_rate.upper:.2%}] (n={s.pass_rate.n_samples}) |",
        f"| Mean Score ({s.mean_score.method}) | {s.mean_score.mean:.4f} | [{s.mean_score.lower:.4f}, {s.mean_score.upper:.4f}] (sd={s.mean_score.std_dev:.4f}) |",
        f"| Numeric Accuracy | {s.numeric_accuracy:.4f} | — |",
        f"| Citation Faithfulness | {s.citation_faithfulness:.4f} | — |",
        f"| Tool Reliability | {s.tool_reliability:.4f} | — |",
        f"| Abstention & Safety | {s.abstention_accuracy:.4f} | — |",
        f"| Receipt Verification Rate | {s.receipt_verification_rate:.2%} | — |",
        f"| Total Cost (USD) | \\${s.total_cost_usd:.6f} | mean \\${s.mean_cost_per_task_usd:.6f}/eval |",
        f"| Latency (ms) | mean {s.mean_latency_ms:.2f} ms | p95 {s.p95_latency_ms:.2f} ms |",
        f"| Total Tokens | {s.total_tokens} | — |",
        "",
        "## Failure Types",
    ]
    if s.failure_type_counts:
        lines.append("| Failure Type | Count |")
        lines.append("|---|---|")
        for ft, count in s.failure_type_counts.items():
            lines.append(f"| `{ft}` | {count} |")
    else:
        lines.append("No failures recorded.")

    if report.baseline_comparison is not None:
        bc = report.baseline_comparison
        lines.extend(
            [
                "",
                "## Baseline Comparison",
                f"- **Baseline Report:** `{bc.baseline_report_id}`",
                f"- **Pass Rate Delta:** `{bc.pass_rate_delta:+.4f}`",
                f"- **Mean Score Delta:** `{bc.mean_score_delta:+.4f}`",
                f"- **Within Tolerance ({bc.tolerance:.3f}):** `{bc.within_tolerance}`",
                f"- **Notes:** {bc.notes}",
            ]
        )

    lines.extend(
        [
            "",
            "## Task-Level Results",
            "| Task ID | Seed | Category | Passed | Score | Failures | Faults | Cost (USD) | Latency (ms) |",
            "|---|---:|---|---:|---:|---|---|---:|---:|",
        ]
    )
    for res in report.task_results:
        fails = ", ".join(f.value for f in res.failure_types) or "—"
        faults = ", ".join(res.faults_triggered) or "—"
        lines.append(
            f"| `{res.task_id}` | {res.seed} | `{res.category.value}` | "
            f"{'PASS' if res.passed else 'FAIL'} | {res.overall_score:.4f} | {fails} | {faults} | "
            f"\\${res.cost_usd:.6f} | {res.latency_ms:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_evaluation_artifacts(
    *,
    out_dir: Path,
    report: EvaluationReport,
    bundle: ReplayBundle,
    logs: Sequence[dict[str, Any]],
) -> dict[str, Path]:
    """Persist report JSON, Markdown summary, replay bundle, and structured JSONL logs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = out_dir / f"{report.report_id}.report.json"
    report_md_path = out_dir / f"{report.report_id}.report.md"
    bundle_path = out_dir / f"{report.report_id}.replay.json"
    log_path = out_dir / f"{report.report_id}.events.jsonl"

    report_json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    report_md_path.write_text(render_markdown_report(report), encoding="utf-8")
    bundle_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    log_path.write_text(
        "\n".join(json.dumps(entry, sort_keys=True) for entry in logs) + "\n",
        encoding="utf-8",
    )
    return {
        "report_json": report_json_path,
        "report_md": report_md_path,
        "replay_bundle": bundle_path,
        "events_jsonl": log_path,
    }
