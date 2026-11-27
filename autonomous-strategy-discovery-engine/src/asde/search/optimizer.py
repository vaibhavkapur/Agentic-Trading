"""Nested inner-loop parameter tuning with full trial accounting and no holdout leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Protocol

from asde.data.splits import HoldoutGuard
from asde.dsl.schema import StrategySpec
from asde.errors import ASDEError
from asde.evaluation.costs import CostScenario
from asde.evaluation.walk_forward import WalkForwardEvaluator, WalkForwardResult
from asde.search.generator import BoundedCandidateGenerator
from asde.types import DatasetSnapshot, TrialRecord, format_utc


@dataclass
class TuningOutcome:
    """Result of nested inner-loop parameter tuning for a candidate seed."""

    selected_spec: StrategySpec
    best_inner_score: float
    inner_trials: List[TrialRecord]


class OptimizerAdapter(Protocol):
    """Contract for external optimizers (e.g. Optuna or QT-09 Quantum Strategy Optimizer)."""

    def tune_candidate(
        self,
        *,
        run_id: str,
        base_spec: StrategySpec,
        dataset: DatasetSnapshot,
        holdout_guard: HoldoutGuard,
        cost_scenario: CostScenario,
        max_inner_trials: int,
        seed: int,
    ) -> TuningOutcome:
        ...


class NestedParameterTuner:
    """Tunes candidate parameters strictly on inner training folds with risk-regularized objective.

    Objective explicitly penalizes turnover and drawdown rather than optimizing raw return alone,
    and records every inner trial (including failures) for honest multiple-testing accounting.
    """

    def __init__(
        self,
        *,
        generator: BoundedCandidateGenerator,
        evaluator: WalkForwardEvaluator,
        max_annualized_turnover: float = 18.0,
        max_drawdown_limit: float = 0.35,
    ) -> None:
        self.generator = generator
        self.evaluator = evaluator
        self.max_annualized_turnover = max_annualized_turnover
        self.max_drawdown_limit = max_drawdown_limit

    def tune_candidate(
        self,
        *,
        run_id: str,
        base_spec: StrategySpec,
        dataset: DatasetSnapshot,
        holdout_guard: HoldoutGuard,
        cost_scenario: CostScenario,
        max_inner_trials: int,
        seed: int,
    ) -> TuningOutcome:
        neighbors = self.generator.generate_neighbors(
            base_spec,
            max_neighbors=max(1, max_inner_trials),
            seed=seed,
        )
        inner_folds = holdout_guard.manifest.inner_folds
        inner_trials: List[TrialRecord] = []

        best_spec = base_spec
        best_score = -1e9

        for idx, cand in enumerate(neighbors):
            trial_id = f"{run_id}_inner_{base_spec.strategy_id}_{idx + 1}"
            now_utc = format_utc(datetime(2026, 1, 1, tzinfo=timezone.utc))
            try:
                wf: WalkForwardResult = self.evaluator.evaluate_folds(
                    spec=cand,
                    dataset=dataset,
                    folds=inner_folds,
                    holdout_guard=holdout_guard,
                    cost_scenario=cost_scenario,
                    phase="inner_tuning",
                    split_name="inner",
                    seed=seed + idx + 1,
                )
                m = wf.aggregate_metrics
                reasons: List[str] = []
                if m.annualized_turnover > self.max_annualized_turnover:
                    reasons.append(
                        f"excessive_turnover:{m.annualized_turnover:.2f}>{self.max_annualized_turnover:.2f}"
                    )
                if m.max_drawdown > self.max_drawdown_limit:
                    reasons.append(
                        f"excessive_drawdown:{m.max_drawdown:.3f}>{self.max_drawdown_limit:.3f}"
                    )

                # Risk- and stability-penalized score: Sharpe - 0.5*SE - turnover/drawdown penalties
                turnover_pen = max(0.0, m.annualized_turnover - 10.0) * 0.05
                dd_pen = max(0.0, m.max_drawdown - 0.15) * 2.0
                score = m.sharpe_ratio - 0.35 * m.sharpe_se - 0.20 * wf.fold_sharpe_std - turnover_pen - dd_pen

                status = "REJECTED" if reasons else "PASSED"
                inner_trials.append(
                    TrialRecord(
                        trial_id=trial_id,
                        run_id=run_id,
                        strategy_id=cand.strategy_id,
                        family=cand.family,
                        is_baseline=False,
                        phase="inner_tuning",
                        status=status,
                        seed=seed + idx + 1,
                        parameters=dict(cand.parameters),
                        dataset_fingerprint=dataset.fingerprint,
                        split_manifest_hash=holdout_guard.manifest.manifest_hash,
                        cost_scenario=cost_scenario.name,
                        cost_scenario_hash=cost_scenario.fingerprint(),
                        created_at_utc=now_utc,
                        metrics=m.to_dict(),
                        fold_metrics=wf.fold_results,
                        rejection_reasons=reasons,
                    )
                )
                if not reasons and score > best_score:
                    best_score = score
                    best_spec = cand
            except ASDEError as exc:
                inner_trials.append(
                    TrialRecord(
                        trial_id=trial_id,
                        run_id=run_id,
                        strategy_id=cand.strategy_id,
                        family=cand.family,
                        is_baseline=False,
                        phase="inner_tuning",
                        status="FAILED",
                        seed=seed + idx + 1,
                        parameters=dict(cand.parameters),
                        dataset_fingerprint=dataset.fingerprint,
                        split_manifest_hash=holdout_guard.manifest.manifest_hash,
                        cost_scenario=cost_scenario.name,
                        cost_scenario_hash=cost_scenario.fingerprint(),
                        created_at_utc=now_utc,
                        error=exc.to_dict(),
                        rejection_reasons=[exc.code],
                    )
                )

        if best_score <= -1e8:
            best_score = 0.0
        return TuningOutcome(
            selected_spec=best_spec,
            best_inner_score=round(best_score, 6),
            inner_trials=inner_trials,
        )
