"""End-to-end deterministic Autonomous Strategy Discovery Pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from asde.data.fixtures import load_dataset_from_manifest
from asde.data.splits import HoldoutGuard, SplitPolicy, build_split_manifest
from asde.dsl.catalog import build_baseline_spec, load_catalog
from asde.dsl.compiler import SignalCompiler
from asde.dsl.schema import StrategySpec
from asde.errors import ASDEError, GovernanceViolationError
from asde.evaluation.backtester import BacktesterAdapter, BuiltinEventBacktester
from asde.evaluation.costs import CostScenario, load_cost_scenarios
from asde.evaluation.walk_forward import WalkForwardEvaluator
from asde.export.packager import StrategyPackager
from asde.reporting.leaderboard import build_research_leaderboard, render_leaderboard_markdown
from asde.reporting.multiple_testing import evaluate_multiple_testing
from asde.reporting.trial_store import SqliteTrialStore
from asde.search.generator import BoundedCandidateGenerator
from asde.search.optimizer import NestedParameterTuner
from asde.types import DatasetSnapshot, TrialRecord, format_utc, sha256_canonical


@dataclass
class DiscoveryRunResult:
    """Outputs and provenance fingerprints of a complete discovery run."""

    run_id: str
    out_dir: Path
    leaderboard: Dict[str, Any]
    leaderboard_markdown: str
    exported_packages: List[Path]
    health_metrics: Dict[str, Any]
    report_fingerprint: str


class DiscoveryPipeline:
    """Orchestrates constrained discovery, nested tuning, walk-forward eval, reporting, and export."""

    def __init__(
        self,
        *,
        project_root: Path,
        backtester: Optional[BacktesterAdapter] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.backtester = backtester or BuiltinEventBacktester()

    def run_from_config(
        self,
        *,
        config_path: Path,
        out_dir: Path,
        dataset_override: Optional[DatasetSnapshot] = None,
        extra_candidate_specs: Optional[List[StrategySpec]] = None,
        evaluate_locked_holdout_for_top: bool = False,
    ) -> DiscoveryRunResult:
        """Load versioned JSON config and execute a deterministic discovery run."""
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return self.run(
            config=config,
            out_dir=out_dir,
            dataset_override=dataset_override,
            extra_candidate_specs=extra_candidate_specs,
            evaluate_locked_holdout_for_top=evaluate_locked_holdout_for_top,
        )

    def run(
        self,
        *,
        config: Dict[str, Any],
        out_dir: Path,
        dataset_override: Optional[DatasetSnapshot] = None,
        extra_candidate_specs: Optional[List[StrategySpec]] = None,
        evaluate_locked_holdout_for_top: bool = False,
    ) -> DiscoveryRunResult:
        """Execute deterministic strategy discovery with full governance and trial accounting."""
        gov = config.get("governance", {})
        if gov.get("order_execution_enabled", False) is not False:
            raise GovernanceViolationError(
                "order_execution_enabled must be false during discovery runs."
            )
        if gov.get("allow_live_selection", False) is not False:
            raise GovernanceViolationError(
                "allow_live_selection is explicitly prohibited."
            )

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        seed = int(config["seed"])
        catalog_path = self._resolve(config["catalog_path"])
        cost_path = self._resolve(config["cost_scenarios_path"])
        catalog = load_catalog(catalog_path)
        cost_scenarios = load_cost_scenarios(cost_path)

        if dataset_override is not None:
            dataset = dataset_override
        else:
            dataset = load_dataset_from_manifest(self._resolve(config["dataset_manifest_path"]))

        sp_cfg = config["split_policy"]
        split_policy = SplitPolicy(
            train_ratio=float(sp_cfg["train_ratio"]),
            validation_ratio=float(sp_cfg["validation_ratio"]),
            test_ratio=float(sp_cfg["test_ratio"]),
            embargo_bars=int(sp_cfg["embargo_bars"]),
            walk_forward_folds=int(sp_cfg["walk_forward_folds"]),
            inner_tuning_folds=int(sp_cfg["inner_tuning_folds"]),
            min_train_bars=int(sp_cfg["min_train_bars"]),
            min_fold_bars=int(sp_cfg["min_fold_bars"]),
        )
        split_manifest = build_split_manifest(dataset, split_policy)
        holdout_guard = HoldoutGuard(split_manifest)

        eval_cfg = config["evaluation"]
        primary_cost_name = eval_cfg["primary_cost_scenario"]
        primary_cost = cost_scenarios[primary_cost_name]
        stress_cost_objs: List[CostScenario] = [
            cost_scenarios[name] for name in eval_cfg.get("stress_cost_scenarios", [primary_cost_name])
        ]

        # Deterministic run identifier derived from config + dataset + split fingerprints
        run_id = "run_" + sha256_canonical(
            {
                "config": config,
                "dataset_fingerprint": dataset.fingerprint,
                "split_manifest_hash": split_manifest.manifest_hash,
                "catalog_fingerprint": catalog.fingerprint(),
            }
        )[:12]

        trial_db = out_dir / "trial_ledger.sqlite"
        if trial_db.exists():
            trial_db.unlink()
        trial_store = SqliteTrialStore(trial_db)

        compiler = SignalCompiler(catalog)
        evaluator = WalkForwardEvaluator(
            compiler=compiler,
            backtester=self.backtester,
            annualization_factor=int(eval_cfg["annualization_factor"]),
            risk_free_rate_annual=float(eval_cfg["risk_free_rate_annual"]),
            bootstrap_samples=int(eval_cfg["bootstrap_samples"]),
            bootstrap_block_size=int(eval_cfg["bootstrap_block_size"]),
        )
        generator = BoundedCandidateGenerator(catalog)
        tuner = NestedParameterTuner(
            generator=generator,
            evaluator=evaluator,
            max_annualized_turnover=float(eval_cfg["max_annualized_turnover"]),
            max_drawdown_limit=float(eval_cfg["max_drawdown_limit"]),
        )

        fixed_ts_utc = format_utc(datetime(2026, 1, 1, tzinfo=timezone.utc))
        search_cfg = config["search"]

        # 1. Evaluate baselines on identical dataset, folds, and costs
        baseline_rows: List[Dict[str, Any]] = []
        for b_idx, b_name in enumerate(search_cfg.get("include_baselines", [])):
            b_spec = build_baseline_spec(b_name, catalog)
            wf = evaluator.evaluate_folds(
                spec=b_spec,
                dataset=dataset,
                folds=split_manifest.walk_forward_folds,
                holdout_guard=holdout_guard,
                cost_scenario=primary_cost,
                phase="walk_forward_validation",
                split_name="validation",
                seed=seed + 10_000 + b_idx,
            )
            sens = evaluator.evaluate_cost_sensitivity(
                spec=b_spec,
                dataset=dataset,
                folds=split_manifest.walk_forward_folds,
                holdout_guard=holdout_guard,
                scenarios=stress_cost_objs,
                phase="walk_forward_validation",
                split_name="validation",
                seed=seed + 10_000 + b_idx,
            )
            trial_store.record_trial(
                TrialRecord(
                    trial_id=f"{run_id}_baseline_{b_name}",
                    run_id=run_id,
                    strategy_id=b_spec.strategy_id,
                    family=b_spec.family,
                    is_baseline=True,
                    phase="walk_forward_validation",
                    status="PASSED",
                    seed=seed + 10_000 + b_idx,
                    parameters=dict(b_spec.parameters),
                    dataset_fingerprint=dataset.fingerprint,
                    split_manifest_hash=split_manifest.manifest_hash,
                    cost_scenario=primary_cost.name,
                    cost_scenario_hash=primary_cost.fingerprint(),
                    created_at_utc=fixed_ts_utc,
                    metrics=wf.aggregate_metrics.to_dict(),
                    fold_metrics=wf.fold_results,
                )
            )
            baseline_rows.append(
                {
                    "strategy_id": b_spec.strategy_id,
                    "family": b_spec.family,
                    "is_baseline": True,
                    "dataset_fingerprint": wf.dataset_fingerprint,
                    "cost_scenario": wf.cost_scenario,
                    "cost_scenario_hash": wf.cost_scenario_hash,
                    "metrics": wf.aggregate_metrics.to_dict(),
                    "fold_results": wf.fold_results,
                    "positive_fold_fraction": wf.positive_fold_fraction,
                    "worst_fold_sharpe": wf.worst_fold_sharpe,
                    "cost_sensitivity": sens,
                }
            )

        # 2. Generate bounded candidate seeds (+ optional extra specs for fault/scenario tests)
        candidate_seeds = generator.generate(
            families=list(search_cfg["families"]),
            max_candidates=int(search_cfg["max_candidates"]),
            seed=seed,
        )
        if extra_candidate_specs:
            candidate_seeds.extend(extra_candidate_specs)

        max_inner = int(search_cfg.get("max_inner_trials_per_candidate", 3))
        max_turnover = float(eval_cfg["max_annualized_turnover"])
        max_dd = float(eval_cfg["max_drawdown_limit"])

        candidate_rows: List[Dict[str, Any]] = []
        failed_rows: List[Dict[str, Any]] = []
        specs_by_id: Dict[str, StrategySpec] = {}
        seen_outer_ids = set()

        for c_idx, seed_spec in enumerate(candidate_seeds):
            cand_seed = seed + 20_000 + c_idx * 100
            # Nested inner tuning strictly on inner folds inside train
            if max_inner > 1 and not seed_spec.is_baseline and seed_spec.raw_code is None:
                try:
                    tuning = tuner.tune_candidate(
                        run_id=run_id,
                        base_spec=seed_spec,
                        dataset=dataset,
                        holdout_guard=holdout_guard,
                        cost_scenario=primary_cost,
                        max_inner_trials=max_inner,
                        seed=cand_seed,
                    )
                    trial_store.record_many(tuning.inner_trials)
                    tuned_spec = tuning.selected_spec
                    inner_score = tuning.best_inner_score
                except ASDEError:
                    tuned_spec = seed_spec
                    inner_score = 0.0
            else:
                tuned_spec = seed_spec
                inner_score = 0.0

            if tuned_spec.strategy_id in seen_outer_ids:
                continue
            seen_outer_ids.add(tuned_spec.strategy_id)

            outer_trial_id = f"{run_id}_wf_{tuned_spec.strategy_id}_{c_idx + 1}"
            try:
                wf = evaluator.evaluate_folds(
                    spec=tuned_spec,
                    dataset=dataset,
                    folds=split_manifest.walk_forward_folds,
                    holdout_guard=holdout_guard,
                    cost_scenario=primary_cost,
                    phase="walk_forward_validation",
                    split_name="validation",
                    seed=cand_seed + 50,
                )
                sens = evaluator.evaluate_cost_sensitivity(
                    spec=tuned_spec,
                    dataset=dataset,
                    folds=split_manifest.walk_forward_folds,
                    holdout_guard=holdout_guard,
                    scenarios=stress_cost_objs,
                    phase="walk_forward_validation",
                    split_name="validation",
                    seed=cand_seed + 50,
                )

                m = wf.aggregate_metrics
                reasons: List[str] = []
                if m.annualized_turnover > max_turnover:
                    reasons.append(f"excessive_turnover:{m.annualized_turnover:.2f}>{max_turnover:.2f}")
                if m.max_drawdown > max_dd:
                    reasons.append(f"excessive_drawdown:{m.max_drawdown:.3f}>{max_dd:.3f}")
                if m.sharpe_ratio <= 0.0:
                    reasons.append(f"non_positive_net_sharpe:{m.sharpe_ratio:.3f}")
                if "stressed_2x" in sens and sens["stressed_2x"]["sharpe_ratio"] <= 0.0:
                    reasons.append("fails_stressed_2x_cost_sensitivity")
                if wf.positive_fold_fraction < 0.50:
                    reasons.append(f"low_fold_consistency:{wf.positive_fold_fraction:.2f}<0.50")

                trial_status = "REJECTED" if reasons else "PASSED"
                trial_store.record_trial(
                    TrialRecord(
                        trial_id=outer_trial_id,
                        run_id=run_id,
                        strategy_id=tuned_spec.strategy_id,
                        family=tuned_spec.family,
                        is_baseline=False,
                        phase="walk_forward_validation",
                        status=trial_status,
                        seed=cand_seed + 50,
                        parameters=dict(tuned_spec.parameters),
                        dataset_fingerprint=dataset.fingerprint,
                        split_manifest_hash=split_manifest.manifest_hash,
                        cost_scenario=primary_cost.name,
                        cost_scenario_hash=primary_cost.fingerprint(),
                        created_at_utc=fixed_ts_utc,
                        metrics=m.to_dict(),
                        fold_metrics=wf.fold_results,
                        rejection_reasons=reasons,
                    )
                )

                specs_by_id[tuned_spec.strategy_id] = tuned_spec
                candidate_rows.append(
                    {
                        "strategy_id": tuned_spec.strategy_id,
                        "family": tuned_spec.family,
                        "parameters": dict(tuned_spec.parameters),
                        "inner_tuning_score": inner_score,
                        "dataset_fingerprint": wf.dataset_fingerprint,
                        "cost_scenario": wf.cost_scenario,
                        "cost_scenario_hash": wf.cost_scenario_hash,
                        "metrics": m.to_dict(),
                        "fold_results": wf.fold_results,
                        "positive_fold_fraction": wf.positive_fold_fraction,
                        "worst_fold_sharpe": wf.worst_fold_sharpe,
                        "fold_sharpe_std": wf.fold_sharpe_std,
                        "cost_sensitivity": sens,
                        "rejection_reasons": reasons,
                        "governance_status": "PENDING_MT",
                    }
                )
            except ASDEError as exc:
                err_dict = exc.to_dict()
                trial_store.record_trial(
                    TrialRecord(
                        trial_id=outer_trial_id,
                        run_id=run_id,
                        strategy_id=tuned_spec.strategy_id,
                        family=tuned_spec.family,
                        is_baseline=False,
                        phase="walk_forward_validation",
                        status="FAILED",
                        seed=cand_seed + 50,
                        parameters=dict(tuned_spec.parameters),
                        dataset_fingerprint=dataset.fingerprint,
                        split_manifest_hash=split_manifest.manifest_hash,
                        cost_scenario=primary_cost.name,
                        cost_scenario_hash=primary_cost.fingerprint(),
                        created_at_utc=fixed_ts_utc,
                        error=err_dict,
                        rejection_reasons=[exc.code],
                    )
                )
                failed_rows.append(
                    {
                        "strategy_id": tuned_spec.strategy_id,
                        "family": tuned_spec.family,
                        "parameters": dict(tuned_spec.parameters),
                        "governance_status": "FAILED",
                        "error": err_dict,
                        "rejection_reasons": [exc.code],
                    }
                )

        # 3. Multiple-testing adjustment across ALL candidate trials (inner + outer + failed)
        accounting = trial_store.accounting_summary(run_id=run_id)
        mt_inputs = [
            {
                "strategy_id": r["strategy_id"],
                "sharpe_ratio": r["metrics"]["sharpe_ratio"],
                "num_bars": r["metrics"]["num_bars"],
                "skewness": r["metrics"]["skewness"],
                "kurtosis": r["metrics"]["kurtosis"],
            }
            for r in candidate_rows
        ]
        mt_stats = evaluate_multiple_testing(
            candidate_entries=mt_inputs,
            total_trials_accounted=max(1, accounting["candidate_trials_total"]),
            fdr_alpha=float(eval_cfg["fdr_alpha"]),
            min_dsr_prob=float(eval_cfg["min_deflated_sharpe_prob"]),
            annualization_factor=int(eval_cfg["annualization_factor"]),
        )

        # Finalize candidate governance status incorporating DSR multiple-testing check
        for row in candidate_rows:
            mt = mt_stats[row["strategy_id"]]
            if not mt.passes_dsr:
                row["rejection_reasons"].append(
                    f"failed_deflated_sharpe:{mt.dsr_probability:.3f}<{float(eval_cfg['min_deflated_sharpe_prob']):.2f}"
                )
            row["governance_status"] = "REJECTED" if row["rejection_reasons"] else "ELIGIBLE_FOR_REVIEW"

        # 4. Verify zero holdout reads during selection, then lock selection
        if holdout_guard.holdout_reads_during_selection != 0:
            raise GovernanceViolationError("Holdout split was accessed during candidate selection.")
        holdout_guard.lock_selection()

        # Optional one-time post-lock holdout verification for top eligible candidate only
        holdout_verification: Optional[Dict[str, Any]] = None
        eligible_rows = [r for r in candidate_rows if r["governance_status"] == "ELIGIBLE_FOR_REVIEW"]
        eligible_rows.sort(
            key=lambda r: (
                -mt_stats[r["strategy_id"]].dsr_probability,
                -r["metrics"]["sharpe_ratio"],
                r["strategy_id"],
            )
        )
        if evaluate_locked_holdout_for_top and eligible_rows:
            top_id = eligible_rows[0]["strategy_id"]
            top_spec = specs_by_id[top_id]
            ho_res = evaluator.evaluate_locked_holdout(
                spec=top_spec,
                dataset=dataset,
                holdout_guard=holdout_guard,
                cost_scenario=primary_cost,
                seed=seed + 99_999,
            )
            trial_store.record_trial(
                TrialRecord(
                    trial_id=f"{run_id}_holdout_{top_id}",
                    run_id=run_id,
                    strategy_id=top_id,
                    family=top_spec.family,
                    is_baseline=False,
                    phase="holdout_test",
                    status="PASSED",
                    seed=seed + 99_999,
                    parameters=dict(top_spec.parameters),
                    dataset_fingerprint=dataset.fingerprint,
                    split_manifest_hash=split_manifest.manifest_hash,
                    cost_scenario=primary_cost.name,
                    cost_scenario_hash=primary_cost.fingerprint(),
                    created_at_utc=fixed_ts_utc,
                    metrics=ho_res.metrics.to_dict(),
                )
            )
            holdout_verification = {
                "strategy_id": top_id,
                "metrics": ho_res.metrics.to_dict(),
            }
            accounting = trial_store.accounting_summary(run_id=run_id)

        holdout_summary = holdout_guard.summary()
        leaderboard = build_research_leaderboard(
            run_id=run_id,
            dataset_fingerprint=dataset.fingerprint,
            split_manifest_hash=split_manifest.manifest_hash,
            primary_cost_scenario=primary_cost.name,
            cost_scenario_hash=primary_cost.fingerprint(),
            trial_accounting=accounting,
            baseline_rows=baseline_rows,
            candidate_rows=candidate_rows,
            failed_rows=failed_rows,
            mt_stats=mt_stats,
            holdout_summary=holdout_summary,
        )
        if holdout_verification is not None:
            leaderboard["post_lock_holdout_verification"] = holdout_verification

        leaderboard_md = render_leaderboard_markdown(leaderboard)

        # 5. Export packages for review-eligible candidates (and top diagnostic candidate if none pass)
        packager = StrategyPackager()
        exported_packages: List[Path] = []
        export_root = out_dir / "packages"
        for row in leaderboard["candidates"]:
            if row["governance_status"] == "ELIGIBLE_FOR_REVIEW":
                sid = row["strategy_id"]
                ev_payload = dict(row)
                ev_payload["holdout_audit"] = holdout_summary
                ev_payload["baselines"] = baseline_rows
                ev_payload["trial_accounting"] = accounting
                pkg_path = packager.export_candidate(
                    out_dir=export_root,
                    run_id=run_id,
                    spec=specs_by_id[sid],
                    config_snapshot=config,
                    dataset_manifest=dataset.manifest.to_dict(),
                    dataset_fingerprint=dataset.fingerprint,
                    split_manifest=split_manifest.to_dict(),
                    catalog_fingerprint=catalog.fingerprint(),
                    primary_cost_scenario=primary_cost.name,
                    cost_scenario_hash=primary_cost.fingerprint(),
                    evaluation_evidence=ev_payload,
                    seed=seed,
                )
                exported_packages.append(pkg_path)

        # Persist run artifacts
        trial_store.export_jsonl(out_dir / "trials.jsonl", run_id=run_id)
        (out_dir / "split_manifest.json").write_text(
            json.dumps(split_manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (out_dir / "leaderboard.json").write_text(
            json.dumps(leaderboard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (out_dir / "leaderboard.md").write_text(leaderboard_md, encoding="utf-8")

        health_metrics = {
            "run_id": run_id,
            "candidates_evaluated": len(candidate_rows),
            "candidates_eligible_for_review": len(eligible_rows),
            "candidates_rejected": sum(1 for r in candidate_rows if r["governance_status"] == "REJECTED"),
            "candidates_failed": len(failed_rows),
            "baselines_evaluated": len(baseline_rows),
            "total_trials_recorded": accounting["total_trials_recorded"],
            "holdout_reads_during_selection": holdout_summary["holdout_reads_during_selection"],
            "exported_packages_count": len(exported_packages),
            "order_execution_enabled": False,
        }
        (out_dir / "health_metrics.json").write_text(
            json.dumps(health_metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        report_fp = sha256_canonical(leaderboard)
        return DiscoveryRunResult(
            run_id=run_id,
            out_dir=out_dir,
            leaderboard=leaderboard,
            leaderboard_markdown=leaderboard_md,
            exported_packages=exported_packages,
            health_metrics=health_metrics,
            report_fingerprint=report_fp,
        )

    def _resolve(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else (self.project_root / p)
