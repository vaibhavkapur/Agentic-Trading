"""Cost-aware point-in-time backtester and external backtester adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol

from asde.dsl.compiler import CompiledSignals
from asde.errors import EvaluationError
from asde.evaluation.costs import CostScenario
from asde.evaluation.metrics import compute_metrics
from asde.types import DatasetSnapshot, EvaluationMetrics


@dataclass
class BacktestResult:
    """Detailed backtest execution trace and summary metrics for a chronological slice."""

    strategy_id: str
    dataset_fingerprint: str
    cost_scenario: str
    cost_scenario_hash: str
    start_idx: int
    end_idx: int
    timestamps_utc: List[str]
    net_returns: List[float]
    gross_returns: List[float]
    turnovers: List[float]
    cost_drags: List[float]
    equity_curve: List[float]
    metrics: EvaluationMetrics


class BacktesterAdapter(Protocol):
    """Contract for plugging in an external event-driven backtester (e.g. TS-06)."""

    def run_slice(
        self,
        *,
        dataset: DatasetSnapshot,
        signals: CompiledSignals,
        cost_scenario: CostScenario,
        start_idx: int,
        end_idx: int,
        annualization_factor: int = 252,
        risk_free_rate_annual: float = 0.02,
        bootstrap_samples: int = 200,
        bootstrap_block_size: int = 10,
        seed: int = 42,
    ) -> BacktestResult:
        ...


class BuiltinEventBacktester:
    """Deterministic bar-by-bar cost-aware reference backtester.

    Execution semantics:
    - Target weights target_weights[t] are strictly computed from bars <= t - signal_lag_bars.
    - Rebalancing from drifted prior weights to target_weights[t] incurs explicit commission,
      half-spread, slippage, and non-linear market impact costs at bar t.
    - Portfolio earns close-to-close asset returns from bar t-1 to bar t on target_weights[t],
      plus risk-free interest on uninvested cash balance (1 - net_weight), minus short borrow.
    """

    def run_slice(
        self,
        *,
        dataset: DatasetSnapshot,
        signals: CompiledSignals,
        cost_scenario: CostScenario,
        start_idx: int,
        end_idx: int,
        annualization_factor: int = 252,
        risk_free_rate_annual: float = 0.02,
        bootstrap_samples: int = 200,
        bootstrap_block_size: int = 10,
        seed: int = 42,
    ) -> BacktestResult:
        if start_idx < 1 or end_idx <= start_idx or end_idx > dataset.num_bars:
            raise EvaluationError(
                f"Invalid backtest slice [{start_idx}, {end_idx}) for dataset of {dataset.num_bars} bars."
            )
        if len(signals.target_weights) != dataset.num_bars:
            raise EvaluationError("CompiledSignals length does not match dataset bar count.")

        symbols = dataset.symbols
        closes = {s: [b.close for b in dataset.bars_by_symbol[s]] for s in symbols}
        rf_bar = risk_free_rate_annual / float(annualization_factor)

        prev_weights: Dict[str, float] = {s: 0.0 for s in symbols}
        equity = 1.0

        net_returns: List[float] = []
        gross_returns: List[float] = []
        turnovers: List[float] = []
        cost_drags: List[float] = []
        equity_curve: List[float] = []
        timestamps: List[str] = []

        for t in range(start_idx, end_idx):
            target = signals.target_weights[t]
            traded_notional = sum(abs(target[s] - prev_weights[s]) for s in symbols)
            short_notional = sum(abs(min(0.0, target[s])) for s in symbols)
            cost = cost_scenario.bar_cost(
                traded_notional_fraction=traded_notional,
                short_notional_fraction=short_notional,
                annualization_factor=annualization_factor,
            )

            asset_pnl = 0.0
            asset_rets: Dict[str, float] = {}
            for s in symbols:
                r_s = closes[s][t] / closes[s][t - 1] - 1.0
                asset_rets[s] = r_s
                asset_pnl += target[s] * r_s

            net_exposure = sum(target[s] for s in symbols)
            cash_weight = max(0.0, 1.0 - net_exposure)
            gross_r = asset_pnl + cash_weight * rf_bar
            net_r = gross_r - cost

            # Clamp extreme wipeout at -99.9%
            net_r = max(-0.999, net_r)
            gross_r = max(-0.999, gross_r)
            equity *= (1.0 + net_r)

            # Compute drifted end-of-bar weights for accurate next-bar turnover
            denom = max(1e-9, 1.0 + gross_r)
            drifted: Dict[str, float] = {}
            for s in symbols:
                drifted[s] = target[s] * (1.0 + asset_rets[s]) / denom
            prev_weights = drifted

            net_returns.append(net_r)
            gross_returns.append(gross_r)
            turnovers.append(traded_notional)
            cost_drags.append(cost)
            equity_curve.append(round(equity, 8))
            timestamps.append(dataset.timestamps_utc[t])

        metrics = compute_metrics(
            net_returns=net_returns,
            gross_returns=gross_returns,
            turnovers=turnovers,
            cost_drags=cost_drags,
            annualization_factor=annualization_factor,
            risk_free_rate_annual=risk_free_rate_annual,
            bootstrap_samples=bootstrap_samples,
            bootstrap_block_size=bootstrap_block_size,
            seed=seed,
        )

        return BacktestResult(
            strategy_id=signals.strategy_id,
            dataset_fingerprint=dataset.fingerprint,
            cost_scenario=cost_scenario.name,
            cost_scenario_hash=cost_scenario.fingerprint(),
            start_idx=start_idx,
            end_idx=end_idx,
            timestamps_utc=timestamps,
            net_returns=net_returns,
            gross_returns=gross_returns,
            turnovers=turnovers,
            cost_drags=cost_drags,
            equity_curve=equity_curve,
            metrics=metrics,
        )
