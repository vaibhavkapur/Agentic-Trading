"""Required 6 failure-path scenario tests from plan.md section 5 with retained evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from rarp.critic.critic import CriticConfig, CriticFinding, MetricClaim, ResearchCritic
from rarp.data.fixtures import (
    MarketBar,
    generate_synthetic_fixture,
    load_dataset_with_manifest,
)
from rarp.data.splits import HoldoutGuard, HoldoutReleaseToken, build_chronological_splits
from rarp.domain.dsl import (
    BudgetSpec,
    CostModelSpec,
    ExperimentSpec,
    HypothesisSpec,
    SplitSpec,
    StopConditionsSpec,
    load_strategy_catalog,
)
from rarp.domain.errors import (
    BudgetExhaustedError,
    DuplicateHypothesisError,
    HallucinatedMetricError,
    HoldoutAccessError,
    LeakageError,
    ReviewGateError,
    WorkerCrashError,
)
from rarp.domain.types import RunStatus, utc_now_iso
from rarp.governance.review import PromotionGate
from rarp.governance.signing import ArtifactSigner
from rarp.registry.memory import ResearchMemory, compute_trial_adjusted_stats
from rarp.registry.store import RunRecord, RunRegistry
from rarp.scheduler.backtester import ReferenceBacktester
from rarp.scheduler.budget import BudgetTracker
from rarp.scheduler.worker import ExperimentWorker

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "config" / "strategy_catalog.json"


class _HallucinatingCriticAdapter:
    """Injected faulty LLM critic adapter that fabricates Sharpe ratio and metric names."""

    adapter_name = "injected_hallucinating_llm_v0"

    def __init__(self, mode: str) -> None:
        self._mode = mode

    def draft_critique(self, run: RunRecord, trial_stats, config: CriticConfig) -> Dict[str, Any]:
        if self._mode == "wrong_value":
            claims = [
                MetricClaim(
                    run_id=run.run_id,
                    metric_name="validation_sharpe",
                    claimed_value=9.42,  # Fabricated!
                    artifact_sha256=run.artifact_sha256,
                )
            ]
        elif self._mode == "fake_metric_name":
            claims = [
                MetricClaim(
                    run_id=run.run_id,
                    metric_name="guaranteed_live_alpha_pct",
                    claimed_value=42.0,
                    artifact_sha256=run.artifact_sha256,
                )
            ]
        else:
            claims = [
                MetricClaim(
                    run_id=run.run_id,
                    metric_name="validation_sharpe",
                    claimed_value=float(run.metrics["validation_sharpe"]),
                    artifact_sha256="forged_artifact_hash_0000",
                )
            ]
        return {
            "verdict": "CANDIDATE_FOR_REVIEW",
            "summary": "Hallucinated summary",
            "findings": [CriticFinding("FAKE", "INFO", "Fabricated claim", ["validation_sharpe"])],
            "claims": claims,
        }


def run_all_required_scenarios() -> Dict[str, Any]:
    """Execute all 6 required failure-path scenarios and return structured verification evidence."""
    catalog = load_strategy_catalog(CATALOG_PATH)
    evidence: Dict[str, Any] = {
        "generated_at_utc": utc_now_iso(),
        "scenarios": {},
    }

    with tempfile.TemporaryDirectory(prefix="rarp_scenarios_") as tmp:
        root = Path(tmp)
        csv_path, manifest_path, manifest = generate_synthetic_fixture(root / "fixtures", seed=42)
        _, bars_by_symbol = load_dataset_with_manifest(manifest_path)
        split = build_chronological_splits(bars_by_symbol, SplitSpec())

        # ------------------------------------------------------------------
        # Scenario 1: Future-data mutation
        # ------------------------------------------------------------------
        # 1a. Post-manifest CSV content mutation.
        mutated_csv = root / "fixtures" / "mutated_copy"
        mutated_csv.mkdir(parents=True, exist_ok=True)
        (mutated_csv / csv_path.name).write_text(csv_path.read_text(encoding="utf-8") + "SYN_EQ_A,2026-01-01T00:00:00Z,2026-01-01T00:00:00Z,100,101,99,100,1000,USD\n", encoding="utf-8")
        (mutated_csv / manifest_path.name).write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_mutation_error = None
        try:
            load_dataset_with_manifest(mutated_csv / manifest_path.name)
        except LeakageError as exc:
            manifest_mutation_error = exc.to_dict()

        # 1b. Future available_time_utc > event_time_utc injected into worker execution.
        leaked_train = {k: list(v) for k, v in split.train.items()}
        target_bar = leaked_train["SYN_EQ_A"][10]
        leaked_train["SYN_EQ_A"][10] = MarketBar(
            symbol=target_bar.symbol,
            event_time_utc=target_bar.event_time_utc,
            available_time_utc="2029-01-01T00:00:00Z",  # Future availability!
            open_price=target_bar.open_price,
            high_price=target_bar.high_price,
            low_price=target_bar.low_price,
            close_price=target_bar.close_price,
            volume=target_bar.volume,
        )
        reg1 = RunRegistry(root / "s1_reg")
        mem1 = ResearchMemory(catalog)
        budget1 = BudgetTracker(BudgetSpec(), StopConditionsSpec())
        worker1 = ExperimentWorker(ReferenceBacktester(), reg1, budget1)
        hyp1 = HypothesisSpec(
            hypothesis_id="hyp_s1_leak",
            title="Leakage test hypothesis",
            rationale="Verify future data triggers LeakageError",
            family="momentum_crossover",
            parameters={"fast_window": 5, "slow_window": 25, "signal_lag_bars": 1, "vol_target_annual": 0.15},
            universe=("SYN_EQ_A",),
            proposer_id="scenario_runner",
            created_at_utc="2026-01-01T00:00:00Z",
        )
        spec1 = ExperimentSpec(
            experiment_id="exp_s1_leak",
            hypothesis=hyp1,
            data_manifest_id=manifest.manifest_id,
            data_manifest_sha256=manifest.content_sha256,
            split=SplitSpec(),
            cost_model=CostModelSpec("baseline"),
            seed=42,
        )
        pit_leak_error = None
        try:
            worker1.execute(spec1, leaked_train, split.validation, split.split_sha256)
        except LeakageError as exc:
            pit_leak_error = exc.to_dict()
            mem1.record(hyp1, RunStatus.REJECTED, failure_reason=exc.message, error_code=exc.code)

        s1_runs = reg1.list_runs()
        s1_failed = mem1.failed_hypotheses(error_code="LEAKAGE_DETECTED")
        evidence["scenarios"]["future_data_mutation"] = {
            "passed": bool(
                manifest_mutation_error
                and pit_leak_error
                and len(s1_runs) == 1
                and s1_runs[0].status == "REJECTED"
                and len(s1_failed) == 1
            ),
            "manifest_mutation_error": manifest_mutation_error,
            "pit_leak_error": pit_leak_error,
            "recorded_run_status": s1_runs[0].status if s1_runs else None,
            "discoverable_failed_count": len(s1_failed),
        }

        # ------------------------------------------------------------------
        # Scenario 2: Repeated hypotheses (exact & near-duplicate)
        # ------------------------------------------------------------------
        mem2 = ResearchMemory(catalog, near_duplicate_distance=0.05)
        h_orig = HypothesisSpec(
            hypothesis_id="hyp_s2_orig",
            title="Original momentum",
            rationale="Baseline",
            family="momentum_crossover",
            parameters={"fast_window": 10, "slow_window": 40, "signal_lag_bars": 1, "vol_target_annual": 0.15},
            universe=("SYN_EQ_A", "SYN_EQ_B"),
            proposer_id="scenario_runner",
            created_at_utc="2026-01-01T00:00:00Z",
        )
        mem2.record(h_orig, RunStatus.SUCCEEDED, run_id="run_orig", validation_sharpe=0.5)

        h_exact = HypothesisSpec(
            hypothesis_id="hyp_s2_exact_dup",
            title="Disguised exact duplicate",
            rationale="Different title same params",
            family="momentum_crossover",
            parameters={"fast_window": 10, "slow_window": 40, "signal_lag_bars": 1, "vol_target_annual": 0.15},
            universe=("SYN_EQ_B", "SYN_EQ_A"),
            proposer_id="scenario_runner",
            created_at_utc="2026-01-01T00:01:00Z",
        )
        exact_err = None
        try:
            mem2.check_novelty(h_exact, raise_on_duplicate=True)
        except DuplicateHypothesisError as exc:
            exact_err = exc.to_dict()

        h_near = HypothesisSpec(
            hypothesis_id="hyp_s2_near_dup",
            title="Near duplicate",
            rationale="Tiny tweak below novelty threshold",
            family="momentum_crossover",
            parameters={"fast_window": 10, "slow_window": 41, "signal_lag_bars": 1, "vol_target_annual": 0.151},
            universe=("SYN_EQ_A", "SYN_EQ_B"),
            proposer_id="scenario_runner",
            created_at_utc="2026-01-01T00:02:00Z",
        )
        near_err = None
        try:
            mem2.check_novelty(h_near, raise_on_duplicate=True)
        except DuplicateHypothesisError as exc:
            near_err = exc.to_dict()

        evidence["scenarios"]["repeated_hypotheses"] = {
            "passed": bool(exact_err and near_err and not exact_err["details"]["is_near_duplicate"] and near_err["details"]["is_near_duplicate"]),
            "exact_duplicate_error": exact_err,
            "near_duplicate_error": near_err,
        }

        # ------------------------------------------------------------------
        # Scenario 3: Budget exhaustion
        # ------------------------------------------------------------------
        budget3 = BudgetTracker(
            BudgetSpec(max_iterations=5, max_experiments=10, max_cost_usd=0.25, cost_per_experiment_usd=0.10),
            StopConditionsSpec(),
        )
        reg3 = RunRegistry(root / "s3_reg")
        worker3 = ExperimentWorker(ReferenceBacktester(), reg3, budget3)
        exhausted_err = None
        dispatched = 0
        for idx in range(5):
            h = HypothesisSpec(
                hypothesis_id=f"hyp_s3_{idx}",
                title=f"Budget test {idx}",
                rationale="Test budget stop",
                family="momentum_crossover",
                parameters={"fast_window": 4 + idx, "slow_window": 20 + idx * 5, "signal_lag_bars": 1, "vol_target_annual": 0.15},
                universe=("SYN_EQ_A",),
                proposer_id="scenario_runner",
                created_at_utc="2026-01-01T00:00:00Z",
            )
            sp = ExperimentSpec(
                experiment_id=f"exp_s3_{idx}",
                hypothesis=h,
                data_manifest_id=manifest.manifest_id,
                data_manifest_sha256=manifest.content_sha256,
                split=SplitSpec(),
                cost_model=CostModelSpec("baseline"),
                seed=42,
            )
            try:
                worker3.execute(sp, split.train, split.validation, split.split_sha256)
                dispatched += 1
            except BudgetExhaustedError as exc:
                exhausted_err = exc.to_dict()
                break

        snap3 = budget3.snapshot().to_dict()
        evidence["scenarios"]["budget_exhaustion"] = {
            "passed": bool(
                exhausted_err
                and dispatched == 2
                and snap3["cost_usd_used"] <= snap3["max_cost_usd"]
                and snap3["experiments_used"] == 2
            ),
            "dispatched_experiments": dispatched,
            "budget_snapshot": snap3,
            "error": exhausted_err,
        }

        # ------------------------------------------------------------------
        # Scenario 4: Worker crash and retry + idempotent replay
        # ------------------------------------------------------------------
        reg4 = RunRegistry(root / "s4_reg")
        budget4 = BudgetTracker(
            BudgetSpec(max_iterations=3, max_experiments=5, max_cost_usd=1.0, cost_per_experiment_usd=0.10),
            StopConditionsSpec(),
        )

        def crash_on_first_attempt(spec: ExperimentSpec, attempt: int) -> None:
            if attempt == 1:
                raise WorkerCrashError("Simulated SIGKILL / worker crash mid-execution", {"attempt": attempt})

        worker4 = ExperimentWorker(
            ReferenceBacktester(), reg4, budget4, max_retries=2, fault_injector=crash_on_first_attempt
        )
        hyp4 = HypothesisSpec(
            hypothesis_id="hyp_s4_crash",
            title="Crash recovery test",
            rationale="Ensure retry + idempotency",
            family="momentum_crossover",
            parameters={"fast_window": 6, "slow_window": 30, "signal_lag_bars": 1, "vol_target_annual": 0.15},
            universe=("SYN_EQ_A", "SYN_EQ_B"),
            proposer_id="scenario_runner",
            created_at_utc="2026-01-01T00:00:00Z",
        )
        spec4 = ExperimentSpec(
            experiment_id="exp_s4_crash",
            hypothesis=hyp4,
            data_manifest_id=manifest.manifest_id,
            data_manifest_sha256=manifest.content_sha256,
            split=SplitSpec(),
            cost_model=CostModelSpec("baseline"),
            seed=42,
        )
        res4_first = worker4.execute(spec4, split.train, split.validation, split.split_sha256)
        cost_after_first = budget4.snapshot().cost_usd_used
        # Replay identical experiment spec: must return exact run without re-charging budget.
        res4_replay = worker4.execute(spec4, split.train, split.validation, split.split_sha256)
        cost_after_replay = budget4.snapshot().cost_usd_used
        crash_events = [e for e in reg4.list_audit_events() if e["event_type"] == "WORKER_CRASH_CHECKPOINTED"]
        evidence["scenarios"]["worker_crash_and_retry"] = {
            "passed": bool(
                res4_first.run_record.status == "SUCCEEDED"
                and res4_first.attempts == 2
                and not res4_first.replayed_from_registry
                and res4_replay.replayed_from_registry
                and res4_replay.run_record.run_id == res4_first.run_record.run_id
                and len(reg4.list_runs()) == 1
                and cost_after_first == cost_after_replay
                and len(crash_events) == 1
            ),
            "attempts_until_success": res4_first.attempts,
            "final_run_id": res4_first.run_record.run_id,
            "replay_deduplicated": res4_replay.replayed_from_registry,
            "cost_charged_once_usd": cost_after_replay,
            "crash_checkpoint_events": len(crash_events),
        }

        # ------------------------------------------------------------------
        # Scenario 5: Hallucinated metric detection
        # ------------------------------------------------------------------
        critic5 = ResearchCritic(reg4)
        trial_stats5 = compute_trial_adjusted_stats(
            res4_first.run_record.metrics["validation_sharpe"], 90, 1
        )
        hallucination_errors: Dict[str, Any] = {}
        for mode in ("wrong_value", "fake_metric_name", "forged_hash"):
            try:
                critic5.evaluate_run(
                    res4_first.run_record,
                    trial_stats5,
                    adapter_override=_HallucinatingCriticAdapter(mode),
                )
            except HallucinatedMetricError as exc:
                hallucination_errors[mode] = exc.to_dict()

        # Confirm promotion gate blocks promotion when no verified critic report exists.
        gate5 = PromotionGate(reg4, ArtifactSigner(secret_key="s5-key"))
        promo_blocked_err = None
        try:
            gate5.submit_decision(res4_first.run_record.run_id, reviewer_id="reviewer_independent", approve=True)
        except ReviewGateError as exc:
            promo_blocked_err = exc.to_dict()

        hallucination_audit_events = [
            e for e in reg4.list_audit_events() if e["event_type"] == "HALLUCINATED_METRIC_DETECTED"
        ]
        evidence["scenarios"]["hallucinated_metric"] = {
            "passed": bool(
                len(hallucination_errors) == 3
                and promo_blocked_err is not None
                and len(hallucination_audit_events) == 3
                and reg4.get_critic_report_for_run(res4_first.run_record.run_id) is None
            ),
            "detected_modes": sorted(hallucination_errors.keys()),
            "audit_events_logged": len(hallucination_audit_events),
            "promotion_blocked": promo_blocked_err is not None,
        }

        # ------------------------------------------------------------------
        # Scenario 6: Holdout access denial & authorized single-use release
        # ------------------------------------------------------------------
        guard = HoldoutGuard(split)
        denials: Dict[str, Any] = {}
        try:
            guard.access_holdout(caller_id="refiner_agent", purpose="hyperparameter_search", token=None)
        except HoldoutAccessError as exc:
            denials["no_token"] = exc.to_dict()

        try:
            guard.issue_release_token(
                hypothesis_id="hyp_s6",
                proposer_id="proposer_x",
                reviewer_id="proposer_x",  # Proposer trying to self-unlock!
                reason="self unlock attempt",
            )
        except HoldoutAccessError as exc:
            denials["proposer_self_unlock"] = exc.to_dict()

        forged = HoldoutReleaseToken(
            token_id="holdout_tok_forged",
            hypothesis_id="hyp_s6",
            proposer_id="proposer_x",
            reviewer_id="reviewer_y",
            issued_at_utc=utc_now_iso(),
            reason="forged",
            signature="0000",
        )
        try:
            guard.access_holdout(caller_id="refiner_agent", purpose="forged_read", token=forged)
        except HoldoutAccessError as exc:
            denials["forged_token"] = exc.to_dict()

        # Independent reviewer issues single-use token -> succeeds once, then replay is denied.
        valid_token = guard.issue_release_token(
            hypothesis_id="hyp_s6",
            proposer_id="proposer_x",
            reviewer_id="independent_reviewer_z",
            reason="Pre-registered final blinded evaluation",
        )
        holdout_bars = guard.access_holdout(caller_id="sealed_evaluator", purpose="final_eval", token=valid_token)
        try:
            guard.access_holdout(caller_id="sealed_evaluator", purpose="replay_attempt", token=valid_token)
        except HoldoutAccessError as exc:
            denials["reused_token"] = exc.to_dict()

        evidence["scenarios"]["holdout_access_denial"] = {
            "passed": bool(
                len(denials) == 4
                and len(holdout_bars) == len(split.holdout)
                and len(guard.audit_log()) == 5
            ),
            "denials_verified": sorted(denials.keys()),
            "authorized_single_use_succeeded": len(holdout_bars) > 0,
            "audit_log_entries": [e.to_dict() for e in guard.audit_log()],
        }

    evidence["all_passed"] = all(s["passed"] for s in evidence["scenarios"].values())
    return evidence


class TestRequiredScenarios(unittest.TestCase):
    def test_all_six_required_scenarios(self) -> None:
        ev = run_all_required_scenarios()
        self.assertTrue(ev["all_passed"], msg=json.dumps(ev, indent=2))
        for name in (
            "future_data_mutation",
            "repeated_hypotheses",
            "budget_exhaustion",
            "worker_crash_and_retry",
            "hallucinated_metric",
            "holdout_access_denial",
        ):
            self.assertIn(name, ev["scenarios"])
            self.assertTrue(ev["scenarios"][name]["passed"], msg=f"Scenario {name} failed")


if __name__ == "__main__":
    unittest.main()
