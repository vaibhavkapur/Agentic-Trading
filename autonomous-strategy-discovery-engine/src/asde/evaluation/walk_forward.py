"""Cost-aware walk-forward evaluator with robustness checks across non-overlapping periods."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional

from asde.data.splits import FoldSpec, HoldoutGuard
from asde.dsl.compiler import SignalCompiler
from asde.dsl.schema import StrategySpec
from asde.evaluation.backtester import BacktesterAdapter, BacktestResult, BuiltinEventBacktester
from asde.evaluation.costs import CostScenario
from asde.evaluation.metrics import compute_metrics
from asde.types import DatasetSnapshot, EvaluationMetrics


@dataclass
class WalkForwardResult:
    """Aggregated out-of-sample walk-forward evaluation across non-overlapping folds."""

    strategy_spec: StrategySpec
    dataset_fingerprint: str
    split_manifest_hash: str
    cost_scenario: str
    cost_scenario_hash: str
    aggregate_metrics: EvaluationMetrics
    fold_results: List[Dict[str, Any]]
    positive_fold_fraction: float
    worst_fold_sharpe: float
    fold_sharpe_std: float
    net_returns: List[float]
    gross_returns: List[float]
    turnovers: List[float]
    cost_drags: List[float]
    cost_sensitivity: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class WalkForwardEvaluator:
    """Evaluates strategies strictly on authorized non-overlapping walk-forward folds."""

    def __init__(
        self,
        *,
        compiler: SignalCompiler,
        backtester: Optional[BacktesterAdapter] = None,
        annualization_factor: int = 252,
        risk_free_rate_annual: float = 0.02,
        bootstrap_samples: int = 200,
        bootstrap_block_size: int = 10,
    ) -> None:
        self.compiler = compiler
        self.backtester = backtester or BuiltinEventBacktester()
        self.annualization_factor = annualization_factor
        self.risk_free_rate_annual = risk_free_rate_annual
        self.bootstrap_samples = bootstrap_samples
        self.bootstrap_block_size = bootstrap_block_size

    def evaluate_folds(
        self,
        *,
        spec: StrategySpec,
        dataset: DatasetSnapshot,
        folds: List[FoldSpec],
        holdout_guard: HoldoutGuard,
        cost_scenario: CostScenario,
        phase: str,
        split_name: str,
        seed: int,
        injected_lookahead_bars: int = 0,
    ) -> WalkForwardResult:
        """Compile signals once with strict causal lag and evaluate across non-overlapping folds."""
        compiled = self.compiler.compile(
            spec,
            dataset,
            injected_lookahead_bars=injected_lookahead_bars,
        )

        agg_net: List[float] = []
        agg_gross: List[float] = []
        agg_turn: List[float] = []
        agg_cost: List[float] = []
        fold_summaries: List[Dict[str, Any]] = []
        fold_sharpes: List[float] = []

        for f_idx, fold in enumerate(folds):
            s_idx, e_idx = holdout_guard.request_slice(
                split_name=split_name,
                start_idx=fold.val_start,
                end_idx=fold.val_end,
                phase=phase,
                requester=f"WalkForwardEvaluator:{spec.strategy_id}:{fold.fold_id}",
            )
            res = self.backtester.run_slice(
                dataset=dataset,
                signals=compiled,
                cost_scenario=cost_scenario,
                start_idx=s_idx,
                end_idx=e_idx,
                annualization_factor=self.annualization_factor,
                risk_free_rate_annual=self.risk_free_rate_annual,
                bootstrap_samples=min(80, self.bootstrap_samples),
                bootstrap_block_size=self.bootstrap_block_size,
                seed=seed + f_idx + 1,
            )
            agg_net.extend(res.net_returns)
            agg_gross.extend(res.gross_returns)
            agg_turn.extend(res.turnovers)
            agg_cost.extend(res.cost_drags)
            fold_sharpes.append(res.metrics.sharpe_ratio)
            fold_summaries.append(
                {
                    "fold_id": fold.fold_id,
                    "val_start_utc": fold.val_start_utc,
                    "val_end_utc": fold.val_end_utc,
                    "num_bars": res.metrics.num_bars,
                    "sharpe_ratio": res.metrics.sharpe_ratio,
                    "total_return": res.metrics.total_return,
                    "max_drawdown": res.metrics.max_drawdown,
                    "annualized_turnover": res.metrics.annualized_turnover,
                    "total_cost_drag": res.metrics.total_cost_drag,
                }
            )

        agg_metrics = compute_metrics(
            net_returns=agg_net,
            gross_returns=agg_gross,
            turnovers=agg_turn,
            cost_drags=agg_cost,
            annualization_factor=self.annualization_factor,
            risk_free_rate_annual=self.risk_free_rate_annual,
            bootstrap_samples=self.bootstrap_samples,
            bootstrap_block_size=self.bootstrap_block_size,
            seed=seed,
        )

        pos_frac = sum(1 for sr in fold_sharpes if sr > 0.0) / float(len(fold_sharpes)) if fold_sharpes else 0.0
        worst_sr = min(fold_sharpes) if fold_sharpes else 0.0
        if len(fold_sharpes) >= 2:
            m = sum(fold_sharpes) / len(fold_sharpes)
            sr_std = math.sqrt(sum((x - m) ** 2 for x in fold_sharpes) / (len(fold_sharpes) - 1))
        else:
            sr_std = 0.0

        return WalkForwardResult(
            strategy_spec=spec,
            dataset_fingerprint=dataset.fingerprint,
            split_manifest_hash=holdout_guard.manifest.manifest_hash,
            cost_scenario=cost_scenario.name,
            cost_scenario_hash=cost_scenario.fingerprint(),
            aggregate_metrics=agg_metrics,
            fold_results=fold_summaries,
            positive_fold_fraction=round(pos_frac, 4),
            worst_fold_sharpe=round(worst_sr, 6),
            fold_sharpe_std=round(sr_std, 6),
            net_returns=agg_net,
            gross_returns=agg_gross,
            turnovers=agg_turn,
            cost_drags=agg_cost,
        )

    def evaluate_cost_sensitivity(
        self,
        *,
        spec: StrategySpec,
        dataset: DatasetSnapshot,
        folds: List[FoldSpec],
        holdout_guard: HoldoutGuard,
        scenarios: List[CostScenario],
        phase: str,
        split_name: str,
        seed: int,
    ) -> Dict[str, Dict[str, Any]]:
        """Evaluate identical folds across multiple cost scenarios for sensitivity reporting."""
        out: Dict[str, Dict[str, Any]] = {}
        for sc in scenarios:
            wf = self.evaluate_folds(
                spec=spec,
                dataset=dataset,
                folds=folds,
                holdout_guard=holdout_guard,
                cost_scenario=sc,
                phase=phase,
                split_name=split_name,
                seed=seed,
            )
            out[sc.name] = {
                "cost_scenario_hash": sc.fingerprint(),
                "linear_trade_bps": sc.linear_trade_bps,
                "sharpe_ratio": wf.aggregate_metrics.sharpe_ratio,
                "total_return": wf.aggregate_metrics.total_return,
                "cagr": wf.aggregate_metrics.cagr,
                "max_drawdown": wf.aggregate_metrics.max_drawdown,
                "annualized_turnover": wf.aggregate_metrics.annualized_turnover,
                "total_cost_drag": wf.aggregate_metrics.total_cost_drag,
            }
        return out

    def evaluate_locked_holdout(
        self,
        *,
        spec: StrategySpec,
        dataset: DatasetSnapshot,
        holdout_guard: HoldoutGuard,
        cost_scenario: CostScenario,
        seed: int,
    ) -> BacktestResult:
        """One-time evaluation on the locked holdout test split (requires selection lock)."""
        manifest = holdout_guard.manifest
        s_idx, e_idx = holdout_guard.request_slice(
            split_name="test",
            start_idx=manifest.test_start,
            end_idx=manifest.test_end,
            phase="locked_holdout_evaluation",
            requester=f"WalkForwardEvaluator:{spec.strategy_id}:holdout",
        )
        compiled = self.compiler.compile(spec, dataset)
        return self.backtester.run_slice(
            dataset=dataset,
            signals=compiled,
            cost_scenario=cost_scenario,
            start_idx=s_idx,
            end_idx=e_idx,
            annualization_factor=self.annualization_factor,
            risk_free_rate_annual=self.risk_free_rate_annual,
            bootstrap_samples=self.bootstrap_samples,
            bootstrap_block_size=self.bootstrap_block_size,
            seed=seed,
        )
