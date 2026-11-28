"""Reproducible end-to-end demo and acceptance benchmark script.

Runs the reference strategy, adversarial security/resource/leakage/dataset
scenarios, and human-review promotion governance workflow, writing versioned
machine-readable outputs to reports/.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strategy_sandbox import (
    DatasetManifest,
    DockerSandboxRunner,
    ExperimentBudget,
    ExperimentEvaluator,
    OrderIntent,
    PaperPortfolioEngine,
    PromotionDeniedError,
    SandboxExecutionResult,
    StrategyProposal,
    StrategySpec,
    TrialRegistry,
    group_bars_by_timestamp,
    load_sandbox_config,
    runtime_environment_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"
CONFIG_PATH = ROOT / "config" / "default_sandbox_config.json"
REPORTS_DIR = ROOT / "reports"


class _SyntheticLeakyRunner:
    backend_name = "synthetic_leaky_probe"

    def run(
        self,
        *,
        code: str,
        dataset: DatasetManifest,
        spec: StrategySpec,
        budget: ExperimentBudget,
        allowed_imports: list[str],
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        engine = PaperPortfolioEngine(spec)
        steps = group_bars_by_timestamp(dataset)
        orders_by_step: list[list[OrderIntent]] = []
        final_close = steps[-1][1]["SYNTH_A"].close
        for idx, (ts, bar_map) in enumerate(steps):
            orders = (
                [OrderIntent(symbol="SYNTH_A", side="BUY", quantity=100.0, reason="lookahead")]
                if idx == 1 and final_close > 150.0
                else []
            )
            orders_by_step.append(orders)
            engine.process_step(step=idx, timestamp=ts, current_bars=bar_map, orders=orders)
        return (
            SandboxExecutionResult(
                succeeded=True,
                exit_code=0,
                wall_time_sec=0.001,
                steps_executed=len(steps),
                orders_by_step=orders_by_step,
            ),
            engine,
        )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_sandbox_config(CONFIG_PATH)
    dataset = DatasetManifest.model_validate(_load_json(FIXTURES / "reference_dataset.json"))
    spec = StrategySpec.model_validate(_load_json(FIXTURES / "reference_spec.json"))
    proposal = StrategyProposal.model_validate(_load_json(FIXTURES / "reference_proposal.json"))
    expected = _load_json(FIXTURES / "reference_expected.json")
    malicious_ds = DatasetManifest.model_validate(_load_json(FIXTURES / "malicious_dataset.json"))

    evaluator = ExperimentEvaluator(config=cfg)
    registry_dir = REPORTS_DIR / "registry_snapshot"
    # Fresh deterministic snapshot per run
    if registry_dir.exists():
        for p in sorted(registry_dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
    registry = TrialRegistry(registry_dir)

    # 1. Reference oracle scenario
    ref_trial = evaluator.evaluate(
        proposal=proposal,
        spec=spec,
        dataset=dataset,
        reference_expected=expected,
    )
    registry.record_trial(ref_trial)

    # 2. Replay reproducibility verification
    replay_chk = registry.replay_trial(
        trial_id=ref_trial.trial_id,
        proposal=proposal,
        spec=spec,
        dataset=dataset,
        evaluator=evaluator,
        reference_expected=expected,
    )

    # 3. Governance: verify unreviewed promotion blocked, then review & promote
    premature_blocked = False
    try:
        registry.promote_trial(ref_trial.trial_id)
    except PromotionDeniedError:
        premature_blocked = True

    review = registry.record_human_review(
        review_id="demo-review-001",
        trial_id=ref_trial.trial_id,
        reviewer="research-lead-demo",
        decision="APPROVE",
        notes="Demo review: verified reference oracle, leakage, determinism, and accounting hashes.",
    )
    promotion = registry.promote_trial(ref_trial.trial_id, review_id=review.review_id)

    # 4. Adversarial scenarios
    scenarios: dict[str, dict[str, Any]] = {}

    inf_trial = evaluator.evaluate(
        proposal=StrategyProposal(
            proposal_id="demo-inf-loop",
            spec_id=spec.spec_id,
            code="def on_bar(ctx):\n    while True:\n        pass\n",
        ),
        spec=spec,
        dataset=dataset,
        budget=ExperimentBudget(max_wall_time_sec=0.4, max_cpu_time_sec=0.4),
    )
    scenarios["infinite_loop"] = {
        "status": inf_trial.status,
        "code": inf_trial.checks[-1].code,
        "wall_time_sec": inf_trial.telemetry.get("total_eval_sec"),
    }

    mem_trial = evaluator.evaluate(
        proposal=StrategyProposal(
            proposal_id="demo-mem-abuse",
            spec_id=spec.spec_id,
            code="def on_bar(ctx):\n    ctx.state['x'] = [i for i in range(1_500_000)]\n    return []\n",
        ),
        spec=spec,
        dataset=dataset,
        budget=ExperimentBudget(max_wall_time_sec=2.0, max_memory_mb=16),
    )
    scenarios["memory_abuse"] = {
        "status": mem_trial.status,
        "code": mem_trial.checks[-1].code,
        "wall_time_sec": mem_trial.telemetry.get("total_eval_sec"),
    }

    net_trial = evaluator.evaluate(
        proposal=StrategyProposal(
            proposal_id="demo-net-access",
            spec_id=spec.spec_id,
            code="import socket\ndef on_bar(ctx):\n    socket.create_connection(('1.1.1.1', 80))\n    return []\n",
        ),
        spec=spec,
        dataset=dataset,
    )
    net_runtime_trial = evaluator.evaluate(
        proposal=StrategyProposal(
            proposal_id="demo-net-runtime",
            spec_id=spec.spec_id,
            code="import socket\ndef on_bar(ctx):\n    socket.create_connection(('1.1.1.1', 80))\n    return []\n",
        ),
        spec=spec,
        dataset=dataset,
        skip_static_policy=True,
    )
    scenarios["network_access_denial"] = {
        "static_status": net_trial.status,
        "static_code": net_trial.checks[-1].code,
        "runtime_status": net_runtime_trial.status,
        "runtime_code": net_runtime_trial.checks[-1].code,
    }

    fs_runtime_trial = evaluator.evaluate(
        proposal=StrategyProposal(
            proposal_id="demo-fs-runtime",
            spec_id=spec.spec_id,
            code="def on_bar(ctx):\n    open('/etc/passwd').read()\n    return []\n",
        ),
        spec=spec,
        dataset=dataset,
        skip_static_policy=True,
    )
    scenarios["filesystem_access_denial"] = {
        "runtime_status": fs_runtime_trial.status,
        "runtime_code": fs_runtime_trial.checks[-1].code,
    }

    leaky_eval = ExperimentEvaluator(config=cfg, runner=_SyntheticLeakyRunner())
    leaky_trial = leaky_eval.evaluate(
        proposal=StrategyProposal(
            proposal_id="demo-leaky",
            spec_id=spec.spec_id,
            code="def on_bar(ctx):\n    return []\n",
        ),
        spec=spec,
        dataset=dataset,
    )
    scenarios["future_data_leakage_probe"] = {
        "status": leaky_trial.status,
        "code": next(c.code for c in leaky_trial.checks if c.name == "future_data_leakage"),
    }

    mal_ds_trial = evaluator.evaluate(proposal=proposal, spec=spec, dataset=malicious_ds)
    scenarios["malicious_dataset_instructions"] = {
        "status": mal_ds_trial.status,
        "code": mal_ds_trial.checks[-1].code,
        "sandbox_invocations": mal_ds_trial.telemetry["counters"]["sandbox_invocations"],
    }

    # 5. Latency benchmark across 5 full reference evaluations
    eval_latencies_ms: list[float] = []
    primary_exec_ms: list[float] = []
    peak_mem_bytes: list[int] = []
    for _ in range(5):
        t0 = time.monotonic()
        tr = evaluator.evaluate(proposal=proposal, spec=spec, dataset=dataset, reference_expected=expected)
        eval_latencies_ms.append(round((time.monotonic() - t0) * 1000.0, 2))
        primary_exec_ms.append(round(float(tr.telemetry.get("primary_wall_time_sec", 0.0)) * 1000.0, 2))
        peak_mem_bytes.append(int(tr.telemetry.get("peak_traced_memory_bytes", 0)))

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    env_snapshot = runtime_environment_snapshot(cfg.sandbox_backend)

    demo_output = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "provenance_note": "Observed measurements on synthetic offline fixtures; no live capital, market feeds, or real credentials.",
        "config": cfg.model_dump(mode="json"),
        "runtime_env": env_snapshot,
        "docker_available": DockerSandboxRunner.is_available(),
        "reference_trial": {
            "trial_id": ref_trial.trial_id,
            "status": ref_trial.status,
            "code_sha256": ref_trial.code_sha256,
            "dataset_sha256": ref_trial.dataset_sha256,
            "input_bundle_sha256": ref_trial.input_bundle_sha256,
            "output_sha256": ref_trial.output_sha256,
            "accounting": ref_trial.accounting.model_dump(mode="json") if ref_trial.accounting else None,
            "reference_expected": expected,
            "checks": [c.model_dump(mode="json") for c in ref_trial.checks],
            "telemetry": ref_trial.telemetry,
        },
        "replay_verification": replay_chk.model_dump(mode="json"),
        "governance": {
            "unreviewed_promotion_blocked": premature_blocked,
            "review": review.model_dump(mode="json"),
            "promotion": promotion.model_dump(mode="json"),
        },
        "adversarial_scenarios": scenarios,
    }

    benchmark_output = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "runtime_env": env_snapshot,
        "runs": len(eval_latencies_ms),
        "full_evaluation_wall_ms": {
            "samples": eval_latencies_ms,
            "mean": round(statistics.fmean(eval_latencies_ms), 2),
            "median": round(statistics.median(eval_latencies_ms), 2),
            "max": max(eval_latencies_ms),
        },
        "single_sandbox_exec_wall_ms": {
            "samples": primary_exec_ms,
            "mean": round(statistics.fmean(primary_exec_ms), 2),
            "median": round(statistics.median(primary_exec_ms), 2),
            "max": max(primary_exec_ms),
        },
        "peak_traced_memory_bytes": {
            "samples": peak_mem_bytes,
            "max": max(peak_mem_bytes),
        },
    }

    (REPORTS_DIR / "demo_results.json").write_text(
        json.dumps(demo_output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (REPORTS_DIR / "benchmark_results.json").write_text(
        json.dumps(benchmark_output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("=== AI Strategy Code Generation Sandbox — Demo Summary ===")
    print(f"Reference trial ID : {ref_trial.trial_id}")
    print(f"Reference status   : {ref_trial.status}")
    assert ref_trial.accounting is not None
    print(
        f"Final equity       : ${ref_trial.accounting.final_equity:,.4f} "
        f"(expected ${expected['final_equity']:,.4f}, "
        f"identity_err={ref_trial.accounting.max_accounting_identity_error:.2e})"
    )
    print(f"Replay match       : {replay_chk.passed}")
    print(f"Governance gate    : unreviewed_blocked={premature_blocked}, promoted={promotion.promoted}")
    print(f"Adversarial checks : {json.dumps(scenarios)}")
    print(
        f"Benchmark (5 runs) : median full eval={benchmark_output['full_evaluation_wall_ms']['median']} ms, "
        f"median single sandbox exec={benchmark_output['single_sandbox_exec_wall_ms']['median']} ms"
    )
    print(f"Docker available   : {DockerSandboxRunner.is_available()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
