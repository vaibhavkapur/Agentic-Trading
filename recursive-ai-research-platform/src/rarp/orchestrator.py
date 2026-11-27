"""End-to-end auditable recursive research loop orchestrator and deterministic replayer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from rarp.critic.critic import CriticConfig, CriticReport, ResearchCritic
from rarp.critic.refiner import DeterministicRefiner, HypothesisRefiner
from rarp.data.fixtures import load_dataset_with_manifest
from rarp.data.splits import HoldoutGuard, build_chronological_splits
from rarp.domain.dsl import (
    BudgetSpec,
    CostModelSpec,
    ExperimentSpec,
    HypothesisSpec,
    SplitSpec,
    StopConditionsSpec,
    load_strategy_catalog,
)
from rarp.domain.errors import BudgetExhaustedError, DuplicateHypothesisError, RARPError
from rarp.domain.types import PromotionTarget, RunStatus, utc_now_iso
from rarp.governance.review import PaperSandboxPackage, PromotionGate, ReviewDecision
from rarp.governance.signing import ArtifactSigner, SignedResearchArtifact
from rarp.registry.memory import ResearchMemory
from rarp.registry.store import RunRecord, RunRegistry
from rarp.scheduler.backtester import BacktesterAdapter, TS14BacktesterAdapter
from rarp.scheduler.budget import BudgetTracker
from rarp.scheduler.dag import DAGNode, NodeType, ResearchDAG
from rarp.scheduler.worker import ExperimentWorker


@dataclass
class ResearchSessionResult:
    session_id: str
    stop_reason: str
    data_manifest_id: str
    data_manifest_sha256: str
    split_sha256: str
    budget_snapshot: Dict[str, Any]
    dag: Dict[str, Any]
    runs: List[Dict[str, Any]]
    critic_reports: List[Dict[str, Any]]
    memory_entries: List[Dict[str, Any]]
    failed_hypotheses: List[Dict[str, Any]]
    best_run_id: Optional[str]
    signed_research_artifact: Optional[Dict[str, Any]]
    review_decision: Optional[Dict[str, Any]]
    paper_sandbox_package: Optional[Dict[str, Any]]
    registry_hash_chain_valid: bool
    holdout_metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ResearchLoopOrchestrator:
    """Coordinates the full bounded, auditable recursive AI research loop."""

    def __init__(
        self,
        config_dir: Path,
        manifest_path: Path,
        state_dir: Path,
        backtester: Optional[BacktesterAdapter] = None,
        proposer_id: str = "rarp_research_loop_v1",
        signing_key: Optional[str] = None,
    ) -> None:
        self.config_dir = config_dir
        self.manifest_path = manifest_path
        self.state_dir = state_dir
        self.proposer_id = proposer_id

        self.research_config = json.loads((config_dir / "research_config.json").read_text(encoding="utf-8"))
        self.cost_scenarios = json.loads((config_dir / "cost_scenarios.json").read_text(encoding="utf-8"))
        self.catalog = load_strategy_catalog(config_dir / "strategy_catalog.json")

        self.manifest, self.bars_by_symbol = load_dataset_with_manifest(manifest_path)

        split_cfg = self.research_config["split"]
        self.split_spec = SplitSpec(
            train_ratio=float(split_cfg["train_ratio"]),
            validation_ratio=float(split_cfg["validation_ratio"]),
            holdout_ratio=float(split_cfg["holdout_ratio"]),
            embargo_bars=int(split_cfg["embargo_bars"]),
        )
        self.chronological_split = build_chronological_splits(self.bars_by_symbol, self.split_spec)
        self.holdout_guard = HoldoutGuard(self.chronological_split)

        default_cost_name = self.cost_scenarios["default_scenario"]
        c_cfg = self.cost_scenarios["scenarios"][default_cost_name]
        self.cost_model = CostModelSpec(
            scenario_name=default_cost_name,
            currency=c_cfg["currency"],
            commission_bps=float(c_cfg["commission_bps"]),
            half_spread_bps=float(c_cfg["half_spread_bps"]),
            slippage_bps=float(c_cfg["slippage_bps"]),
            annual_borrow_bps=float(c_cfg["annual_borrow_bps"]),
        )

        b_cfg = self.research_config["budget"]
        self.budget_spec = BudgetSpec(
            max_iterations=int(b_cfg["max_iterations"]),
            max_experiments=int(b_cfg["max_experiments"]),
            max_cost_usd=float(b_cfg["max_cost_usd"]),
            cost_per_experiment_usd=float(b_cfg["cost_per_experiment_usd"]),
            max_compute_seconds=float(b_cfg["max_compute_seconds"]),
            max_llm_tokens=int(b_cfg["max_llm_tokens"]),
        )
        s_cfg = self.research_config["stop_conditions"]
        self.stop_spec = StopConditionsSpec(
            max_consecutive_failures=int(s_cfg["max_consecutive_failures"]),
            min_improvement_sharpe=float(s_cfg["min_improvement_sharpe"]),
            patience_rounds=int(s_cfg["patience_rounds"]),
            near_duplicate_distance=float(s_cfg["near_duplicate_distance"]),
        )
        crit_cfg = self.research_config["critic"]
        self.critic_config = CriticConfig(
            metric_tolerance=float(crit_cfg["metric_tolerance"]),
            min_trade_count=int(crit_cfg["min_trade_count"]),
            max_drawdown_limit=float(crit_cfg["max_drawdown_limit"]),
            min_validation_sharpe=float(crit_cfg["min_validation_sharpe"]),
            max_train_val_sharpe_gap=float(crit_cfg["max_train_val_sharpe_gap"]),
        )

        self.registry = RunRegistry(state_dir)
        self.budget = BudgetTracker(self.budget_spec, self.stop_spec)
        self.memory = ResearchMemory(
            self.catalog,
            near_duplicate_distance=self.stop_spec.near_duplicate_distance,
        )
        self.backtester: BacktesterAdapter = backtester or TS14BacktesterAdapter()
        self.worker = ExperimentWorker(self.backtester, self.registry, self.budget)
        self.critic = ResearchCritic(self.registry, self.critic_config)
        self.seed_proposer = DeterministicRefiner()
        self.refiner = HypothesisRefiner(self.catalog, self.seed_proposer)
        self.signer = ArtifactSigner(secret_key=signing_key, key_id="rarp_session_hmac_v1")
        self.promotion_gate = PromotionGate(self.registry, self.signer)

    def run_session(
        self,
        session_id: str = "session_demo_001",
        independent_reviewer_id: Optional[str] = None,
        approve_paper_sandbox: bool = False,
        review_notes: str = "Independent review completed for paper sandbox only.",
    ) -> ResearchSessionResult:
        dag = ResearchDAG(dag_id=f"dag_{session_id}")
        data_node = dag.add_node(
            DAGNode(
                node_id="node_validate_data",
                node_type=NodeType.VALIDATE_DATA,
                label=f"Validate {self.manifest.manifest_id}",
                status=RunStatus.SUCCEEDED,
                metadata={
                    "manifest_id": self.manifest.manifest_id,
                    "content_sha256": self.manifest.content_sha256,
                    "split_sha256": self.holdout_guard.split_sha256,
                },
            )
        )

        seed = int(self.research_config["seed"])
        capital = float(self.research_config["initial_capital_usd"])
        val_bars_count = len(next(iter(self.holdout_guard.get_validation().values())))

        queue: List[tuple[HypothesisSpec, str]] = []
        for h in self.seed_proposer.propose_initial_seed_hypotheses(
            universe=self.manifest.symbols,
            proposer_id=self.proposer_id,
            catalog=self.catalog,
        ):
            pnode = dag.add_node(
                DAGNode(
                    node_id=f"propose_{h.hypothesis_id}",
                    node_type=NodeType.PROPOSE,
                    label=h.title,
                    hypothesis_id=h.hypothesis_id,
                    status=RunStatus.SUCCEEDED,
                )
            )
            dag.add_edge(data_node.node_id, pnode.node_id, "data_validated")
            queue.append((h, pnode.node_id))

        hypothesis_map: Dict[str, HypothesisSpec] = {}
        report_by_run: Dict[str, CriticReport] = {}
        run_by_id: Dict[str, RunRecord] = {}
        next_hyp_index = len(queue) + 1
        stop_reason = "QUEUE_EXHAUSTED"

        while queue:
            stop_check = self.budget.check_stop_conditions()
            if stop_check.should_stop:
                stop_reason = stop_check.reason or "STOP_CONDITION_TRIGGERED"
                break

            try:
                iteration = self.budget.reserve_iteration()
            except BudgetExhaustedError:
                stop_reason = "BUDGET_MAX_ITERATIONS_REACHED"
                break

            # Execute up to 2 queued hypotheses per iteration while honoring experiment/cost limits.
            batch = queue[:2]
            queue = queue[2:]
            iter_candidates: List[tuple[HypothesisSpec, RunRecord, CriticReport, str]] = []

            for hyp, source_node_id in batch:
                hyp.validate(self.catalog)
                try:
                    self.memory.check_novelty(hyp, raise_on_duplicate=True)
                except DuplicateHypothesisError as exc:
                    self.registry.record_audit_event(
                        event_type="HYPOTHESIS_REJECTED_DUPLICATE",
                        actor_id="novelty_checker",
                        details=exc.to_dict(),
                    )
                    continue

                exp_node_id = f"exec_{hyp.hypothesis_id}"
                dag.add_node(
                    DAGNode(
                        node_id=exp_node_id,
                        node_type=NodeType.EXECUTE_EXPERIMENT,
                        label=f"Run {hyp.hypothesis_id}",
                        hypothesis_id=hyp.hypothesis_id,
                        status=RunStatus.RUNNING,
                    )
                )
                dag.add_edge(source_node_id, exp_node_id, "execute")

                spec = ExperimentSpec(
                    experiment_id=f"exp_{session_id}_{hyp.hypothesis_id}",
                    hypothesis=hyp,
                    data_manifest_id=self.manifest.manifest_id,
                    data_manifest_sha256=self.manifest.content_sha256,
                    split=self.split_spec,
                    cost_model=self.cost_model,
                    seed=seed,
                    initial_capital_usd=capital,
                    metadata={"iteration": iteration, "session_id": session_id},
                )
                spec.validate(self.catalog)

                try:
                    exec_res = self.worker.execute(
                        spec=spec,
                        train_bars=self.holdout_guard.get_train(),
                        validation_bars=self.holdout_guard.get_validation(),
                        split_sha256=self.holdout_guard.split_sha256,
                    )
                except BudgetExhaustedError:
                    dag.transition(exp_node_id, RunStatus.SKIPPED, metadata_update={"reason": "budget_exhausted"})
                    stop_reason = "BUDGET_EXHAUSTED"
                    queue.clear()
                    break
                except RARPError as exc:
                    dag.transition(exp_node_id, RunStatus.REJECTED, metadata_update={"error": exc.to_dict()})
                    self.memory.record(
                        hypothesis=hyp,
                        status=RunStatus.REJECTED,
                        failure_reason=exc.message,
                        error_code=exc.code,
                    )
                    continue

                run = exec_res.run_record
                run_by_id[run.run_id] = run
                hypothesis_map[hyp.hypothesis_id] = hyp
                dag.transition(exp_node_id, RunStatus(run.status), run_id=run.run_id)

                if run.status != RunStatus.SUCCEEDED.value:
                    self.memory.record(
                        hypothesis=hyp,
                        status=RunStatus(run.status),
                        run_id=run.run_id,
                        failure_reason=run.error_message,
                        error_code=run.error_code,
                    )
                    continue

                val_sharpe = float(run.metrics.get("validation_sharpe", 0.0))
                pre_counts = self.memory.trial_counts()
                from rarp.registry.memory import compute_trial_adjusted_stats

                trial_stats = compute_trial_adjusted_stats(
                    observed_sharpe=val_sharpe,
                    sample_bars=val_bars_count,
                    total_trials=pre_counts["total_trials"] + 1,
                    succeeded_trials=pre_counts["succeeded_trials"] + 1,
                    failed_or_rejected_trials=pre_counts["failed_or_rejected_trials"],
                )

                crit_node_id = f"critique_{hyp.hypothesis_id}"
                dag.add_node(
                    DAGNode(
                        node_id=crit_node_id,
                        node_type=NodeType.CRITIQUE,
                        label=f"Critique {run.run_id}",
                        hypothesis_id=hyp.hypothesis_id,
                        run_id=run.run_id,
                        status=RunStatus.RUNNING,
                    )
                )
                dag.add_edge(exp_node_id, crit_node_id, "critique")

                report = self.critic.evaluate_run(run, trial_stats)
                report_by_run[run.run_id] = report
                dag.transition(
                    crit_node_id,
                    RunStatus.SUCCEEDED,
                    run_id=run.run_id,
                    metadata_update={"verdict": report.verdict, "report_id": report.report_id},
                )

                failure_reason = None
                error_code = None
                if report.verdict == "REJECT":
                    failure_reason = "; ".join(f.message for f in report.findings)
                    error_code = "CRITIC_REJECTED"

                self.memory.record(
                    hypothesis=hyp,
                    status=RunStatus.SUCCEEDED,
                    run_id=run.run_id,
                    validation_sharpe=val_sharpe,
                    critic_verdict=report.verdict,
                    failure_reason=failure_reason,
                    error_code=error_code,
                )
                iter_candidates.append((hyp, run, report, crit_node_id))

            # Propose refined child hypotheses if budget & stop conditions allow.
            if not self.budget.check_stop_conditions().should_stop and iter_candidates:
                # Pick highest validation Sharpe from this iteration to refine.
                iter_candidates.sort(key=lambda item: float(item[1].metrics.get("validation_sharpe", -1e9)), reverse=True)
                parent_hyp, _, parent_report, crit_node_id = iter_candidates[0]
                child = self.refiner.propose_next(
                    parent=parent_hyp,
                    critic_report=parent_report,
                    memory=self.memory,
                    proposer_id=self.proposer_id,
                    next_index=next_hyp_index,
                )
                if child is not None:
                    next_hyp_index += 1
                    ref_node_id = f"refine_{child.hypothesis_id}"
                    dag.add_node(
                        DAGNode(
                            node_id=ref_node_id,
                            node_type=NodeType.REFINE,
                            label=child.title,
                            hypothesis_id=child.hypothesis_id,
                            status=RunStatus.SUCCEEDED,
                        )
                    )
                    dag.add_edge(crit_node_id, ref_node_id, "refine_from_critique")
                    queue.append((child, ref_node_id))

        # Select best candidate and sign a research artifact bundle.
        best_entry = self.memory.best_entry()
        best_run_id = best_entry.run_id if best_entry else None
        signed_artifact: Optional[SignedResearchArtifact] = None
        decision_obj: Optional[ReviewDecision] = None
        paper_pkg: Optional[PaperSandboxPackage] = None

        if best_run_id and best_run_id in run_by_id:
            best_run = run_by_id[best_run_id]
            best_report = report_by_run[best_run_id]
            bundle_payload = {
                "session_id": session_id,
                "run_id": best_run.run_id,
                "hypothesis_id": best_run.hypothesis_id,
                "data_manifest_id": best_run.data_manifest_id,
                "data_manifest_sha256": best_run.data_manifest_sha256,
                "split_sha256": best_run.split_sha256,
                "config_sha256": best_run.config_sha256,
                "metrics": best_run.metrics,
                "critic_report_id": best_report.report_id,
                "critic_report_sha256": best_report.report_sha256,
                "trial_counts": self.memory.trial_counts(),
                "execution_mode": "DISABLED",
                "live_deployment_prohibited": True,
            }
            signed_artifact = self.signer.sign("research_candidate_bundle", bundle_payload)
            self.registry.put_artifact(
                f"signed/{signed_artifact.artifact_id}.json", signed_artifact.to_dict()
            )

            gate_node = dag.add_node(
                DAGNode(
                    node_id="node_human_review_gate",
                    node_type=NodeType.REVIEW_GATE,
                    label=f"Human Review Gate ({best_run.run_id})",
                    hypothesis_id=best_run.hypothesis_id,
                    run_id=best_run.run_id,
                    status=RunStatus.PENDING,
                )
            )
            best_crit_node = f"critique_{best_run.hypothesis_id}"
            if best_crit_node in dag.nodes:
                dag.add_edge(best_crit_node, gate_node.node_id, "submit_for_human_review")

            if independent_reviewer_id:
                decision_obj, paper_pkg = self.promotion_gate.submit_decision(
                    run_id=best_run.run_id,
                    reviewer_id=independent_reviewer_id,
                    approve=approve_paper_sandbox,
                    target_environment=PromotionTarget.PAPER_SANDBOX.value,
                    notes=review_notes,
                    signed_artifact=signed_artifact,
                )
                dag.transition(
                    gate_node.node_id,
                    RunStatus.SUCCEEDED if approve_paper_sandbox else RunStatus.REJECTED,
                    run_id=best_run.run_id,
                    metadata_update={"decision_id": decision_obj.decision_id, "reviewer_id": independent_reviewer_id},
                )

        return ResearchSessionResult(
            session_id=session_id,
            stop_reason=stop_reason,
            data_manifest_id=self.manifest.manifest_id,
            data_manifest_sha256=self.manifest.content_sha256,
            split_sha256=self.holdout_guard.split_sha256,
            budget_snapshot=self.budget.snapshot().to_dict(),
            dag=dag.to_dict(),
            runs=[r.to_dict() for r in self.registry.list_runs()],
            critic_reports=self.registry.list_critic_reports(),
            memory_entries=[e.to_dict() for e in self.memory.all_entries()],
            failed_hypotheses=[e.to_dict() for e in self.memory.failed_hypotheses()],
            best_run_id=best_run_id,
            signed_research_artifact=signed_artifact.to_dict() if signed_artifact else None,
            review_decision=decision_obj.to_dict() if decision_obj else None,
            paper_sandbox_package=paper_pkg.to_dict() if paper_pkg else None,
            registry_hash_chain_valid=self.registry.verify_hash_chain(),
            holdout_metadata=self.holdout_guard.get_metadata(),
        )


def verify_deterministic_reproducibility(
    config_dir: Path,
    manifest_path: Path,
    work_dir: Path,
    tolerance: float = 1e-12,
) -> Dict[str, Any]:
    """Execute the full deterministic research loop twice from scratch and verify exact agreement."""
    dir_a = work_dir / "replay_run_a"
    dir_b = work_dir / "replay_run_b"

    orch_a = ResearchLoopOrchestrator(config_dir, manifest_path, dir_a, signing_key="repro_test_key")
    res_a = orch_a.run_session(session_id="repro_check", independent_reviewer_id="reviewer_alice", approve_paper_sandbox=True)

    orch_b = ResearchLoopOrchestrator(config_dir, manifest_path, dir_b, signing_key="repro_test_key")
    res_b = orch_b.run_session(session_id="repro_check", independent_reviewer_id="reviewer_alice", approve_paper_sandbox=True)

    comparisons: List[Dict[str, Any]] = []
    max_abs_diff = 0.0
    all_match = len(res_a.runs) == len(res_b.runs) and res_a.best_run_id == res_b.best_run_id

    for ra, rb in zip(res_a.runs, res_b.runs):
        run_diffs: Dict[str, float] = {}
        keys = sorted(set(ra["metrics"].keys()) | set(rb["metrics"].keys()))
        for k in keys:
            va = float(ra["metrics"].get(k, 0.0))
            vb = float(rb["metrics"].get(k, 0.0))
            diff = abs(va - vb)
            run_diffs[k] = diff
            if diff > max_abs_diff:
                max_abs_diff = diff
            if diff > tolerance:
                all_match = False
        comparisons.append(
            {
                "run_id_a": ra["run_id"],
                "run_id_b": rb["run_id"],
                "hypothesis_id": ra["hypothesis_id"],
                "idempotency_key_match": ra["idempotency_key"] == rb["idempotency_key"],
                "max_metric_diff": max(run_diffs.values()) if run_diffs else 0.0,
            }
        )

    return {
        "verified_at_utc": utc_now_iso(),
        "tolerance": tolerance,
        "reproducible": all_match and max_abs_diff <= tolerance,
        "max_abs_metric_diff": max_abs_diff,
        "run_count_a": len(res_a.runs),
        "run_count_b": len(res_b.runs),
        "best_run_id_a": res_a.best_run_id,
        "best_run_id_b": res_b.best_run_id,
        "data_manifest_id": res_a.data_manifest_id,
        "data_manifest_sha256": res_a.data_manifest_sha256,
        "split_sha256": res_a.split_sha256,
        "comparisons": comparisons,
    }
