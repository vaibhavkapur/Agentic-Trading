"""Causal, cost-aware deterministic backtester and TS-14 adapter boundary."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, List, Protocol, Sequence

from rarp.data.fixtures import MarketBar, verify_point_in_time_integrity
from rarp.domain.dsl import CostModelSpec, ExperimentSpec, HypothesisSpec
from rarp.domain.errors import PolicyViolationError, RARPValidationError


@dataclass(frozen=True)
class SplitMetrics:
    split_name: str
    bar_count: int
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    annualized_volatility: float
    turnover_daily: float
    trade_count: int
    hit_rate: float
    cost_drag_return: float
    gross_total_return: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestResult:
    train_metrics: SplitMetrics
    validation_metrics: SplitMetrics
    train_returns: List[float]
    validation_returns: List[float]
    flat_metrics: Dict[str, float]
    backtester_name: str
    backtester_version: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "backtester_name": self.backtester_name,
            "backtester_version": self.backtester_version,
            "train_metrics": self.train_metrics.to_dict(),
            "validation_metrics": self.validation_metrics.to_dict(),
            "flat_metrics": dict(sorted(self.flat_metrics.items())),
        }


class BacktesterAdapter(Protocol):
    """Pluggable evaluation interface separating research orchestration from execution engine."""

    name: str
    version: str

    def evaluate(
        self,
        spec: ExperimentSpec,
        train_bars: Dict[str, List[MarketBar]],
        validation_bars: Dict[str, List[MarketBar]],
    ) -> BacktestResult:
        ...

    def evaluate_single_split(
        self,
        hypothesis: HypothesisSpec,
        cost_model: CostModelSpec,
        bars_by_symbol: Dict[str, List[MarketBar]],
        split_name: str,
    ) -> tuple[SplitMetrics, List[float]]:
        ...


def _compute_raw_signals(family: str, params: Dict[str, object], closes: Sequence[float]) -> List[float]:
    """Compute strictly causal target positions in [-1, 1] using only data up to bar t."""
    n = len(closes)
    raw = [0.0] * n

    if family == "momentum_crossover":
        fast = int(params["fast_window"])
        slow = int(params["slow_window"])
        vol_target = float(params["vol_target_annual"])
        for t in range(slow, n):
            fast_ma = sum(closes[t - fast + 1 : t + 1]) / fast
            slow_ma = sum(closes[t - slow + 1 : t + 1]) / slow
            # Realized volatility over slow window for bounded position sizing.
            rets = [
                (closes[k] / closes[k - 1]) - 1.0
                for k in range(max(1, t - slow + 1), t + 1)
            ]
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
            ann_vol = max(0.05, math.sqrt(var_r * 252.0))
            scale = min(1.0, vol_target / ann_vol)
            if fast_ma > slow_ma:
                raw[t] = scale
            elif fast_ma < slow_ma:
                raw[t] = -scale

    elif family == "mean_reversion_zscore":
        lookback = int(params["lookback_window"])
        entry_z = float(params["entry_z"])
        exit_z = float(params["exit_z"])
        pos = 0.0
        for t in range(lookback, n):
            window = closes[t - lookback + 1 : t + 1]
            mean_p = sum(window) / lookback
            var_p = sum((p - mean_p) ** 2 for p in window) / max(1, lookback - 1)
            std_p = math.sqrt(var_p)
            z = 0.0 if std_p <= 1e-12 else (closes[t] - mean_p) / std_p
            if z <= -entry_z:
                pos = 1.0
            elif z >= entry_z:
                pos = -1.0
            elif abs(z) <= exit_z:
                pos = 0.0
            raw[t] = pos

    elif family == "volatility_breakout":
        ch_win = int(params["channel_window"])
        vol_win = int(params["vol_window"])
        mult = float(params["breakout_mult"])
        start = max(ch_win, vol_win)
        for t in range(start, n):
            prev_slice = closes[t - ch_win : t]
            mean_p = sum(prev_slice) / len(prev_slice)
            rets = [
                (closes[k] / closes[k - 1]) - 1.0
                for k in range(max(1, t - vol_win + 1), t + 1)
            ]
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
            std_r = math.sqrt(var_r)
            threshold = mean_p * mult * max(std_r, 1e-4)
            if closes[t] > mean_p + threshold:
                raw[t] = 1.0
            elif closes[t] < mean_p - threshold:
                raw[t] = -1.0
            else:
                raw[t] = raw[t - 1]
    else:
        raise RARPValidationError(f"Unsupported strategy family: {family}")

    # Strictly apply causal execution lag >= 1 bar.
    lag = int(params["signal_lag_bars"])
    if lag < 1:
        raise RARPValidationError("signal_lag_bars must be >= 1")
    lagged = [0.0] * n
    for t in range(lag, n):
        lagged[t] = raw[t - lag]
    return lagged


def _summarize_split(
    split_name: str,
    net_returns: Sequence[float],
    gross_returns: Sequence[float],
    turnovers: Sequence[float],
    trade_count: int,
) -> SplitMetrics:
    n = len(net_returns)
    if n == 0:
        return SplitMetrics(
            split_name=split_name,
            bar_count=0,
            total_return=0.0,
            cagr=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            annualized_volatility=0.0,
            turnover_daily=0.0,
            trade_count=0,
            hit_rate=0.0,
            cost_drag_return=0.0,
            gross_total_return=0.0,
        )

    equity = 1.0
    gross_equity = 1.0
    peak = 1.0
    max_dd = 0.0
    wins = 0
    active_days = 0

    for nr, gr in zip(net_returns, gross_returns):
        equity *= max(1e-6, 1.0 + nr)
        gross_equity *= max(1e-6, 1.0 + gr)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
        if abs(nr) > 1e-12:
            active_days += 1
            if nr > 0:
                wins += 1

    mean_r = sum(net_returns) / n
    var_r = sum((r - mean_r) ** 2 for r in net_returns) / max(1, n - 1)
    std_r = math.sqrt(var_r)
    sharpe = 0.0 if std_r <= 1e-12 else (mean_r / std_r) * math.sqrt(252.0)

    downside = [min(0.0, r) for r in net_returns]
    down_var = sum(d * d for d in downside) / max(1, n - 1)
    down_std = math.sqrt(down_var)
    sortino = 0.0 if down_std <= 1e-12 else (mean_r / down_std) * math.sqrt(252.0)

    years = n / 252.0
    cagr = (equity ** (1.0 / years) - 1.0) if years > 0 else 0.0
    total_return = equity - 1.0
    gross_total_return = gross_equity - 1.0
    cost_drag = gross_total_return - total_return
    turnover_daily = sum(turnovers) / n
    hit_rate = (wins / active_days) if active_days > 0 else 0.0

    return SplitMetrics(
        split_name=split_name,
        bar_count=n,
        total_return=round(total_return, 10),
        cagr=round(cagr, 10),
        sharpe=round(sharpe, 10),
        sortino=round(sortino, 10),
        max_drawdown=round(max_dd, 10),
        annualized_volatility=round(std_r * math.sqrt(252.0), 10),
        turnover_daily=round(turnover_daily, 10),
        trade_count=trade_count,
        hit_rate=round(hit_rate, 10),
        cost_drag_return=round(cost_drag, 10),
        gross_total_return=round(gross_total_return, 10),
    )


class ReferenceBacktester:
    """Deterministic, point-in-time, cost-aware reference backtester."""

    name = "rarp_reference_backtester"
    version = "1.0.0"

    def evaluate_single_split(
        self,
        hypothesis: HypothesisSpec,
        cost_model: CostModelSpec,
        bars_by_symbol: Dict[str, List[MarketBar]],
        split_name: str,
    ) -> tuple[SplitMetrics, List[float]]:
        verify_point_in_time_integrity(bars_by_symbol)
        symbols = [s for s in hypothesis.universe if s in bars_by_symbol]
        if not symbols:
            raise RARPValidationError(
                f"None of hypothesis symbols {hypothesis.universe} found in dataset"
            )

        min_bars = min(len(bars_by_symbol[s]) for s in symbols)
        one_way_cost = cost_model.one_way_bps() / 10_000.0
        daily_borrow_cost = (cost_model.annual_borrow_bps / 10_000.0) / 252.0
        weight = 1.0 / len(symbols)

        positions_by_symbol: Dict[str, List[float]] = {}
        for sym in symbols:
            closes = [b.close_price for b in bars_by_symbol[sym][:min_bars]]
            positions_by_symbol[sym] = _compute_raw_signals(
                hypothesis.family, hypothesis.parameters, closes
            )

        net_returns: List[float] = []
        gross_returns: List[float] = []
        turnovers: List[float] = []
        trade_count = 0

        for t in range(1, min_bars):
            port_gross = 0.0
            port_cost = 0.0
            port_turnover = 0.0
            for sym in symbols:
                bars = bars_by_symbol[sym]
                prev_close = bars[t - 1].close_price
                curr_close = bars[t].close_price
                asset_ret = (curr_close / prev_close) - 1.0

                pos_t = positions_by_symbol[sym][t]
                pos_prev = positions_by_symbol[sym][t - 1]
                delta = abs(pos_t - pos_prev)
                if delta > 1e-9:
                    trade_count += 1

                port_gross += weight * pos_t * asset_ret
                port_turnover += weight * delta
                short_borrow = weight * abs(min(0.0, pos_t)) * daily_borrow_cost
                port_cost += weight * delta * one_way_cost + short_borrow

            gross_returns.append(port_gross)
            net_returns.append(port_gross - port_cost)
            turnovers.append(port_turnover)

        metrics = _summarize_split(
            split_name=split_name,
            net_returns=net_returns,
            gross_returns=gross_returns,
            turnovers=turnovers,
            trade_count=trade_count,
        )
        return metrics, net_returns

    def evaluate(
        self,
        spec: ExperimentSpec,
        train_bars: Dict[str, List[MarketBar]],
        validation_bars: Dict[str, List[MarketBar]],
    ) -> BacktestResult:
        train_m, train_rets = self.evaluate_single_split(
            spec.hypothesis, spec.cost_model, train_bars, "train"
        )
        val_m, val_rets = self.evaluate_single_split(
            spec.hypothesis, spec.cost_model, validation_bars, "validation"
        )
        flat_metrics: Dict[str, float] = {
            "train_sharpe": train_m.sharpe,
            "train_total_return": train_m.total_return,
            "train_max_drawdown": train_m.max_drawdown,
            "train_trade_count": float(train_m.trade_count),
            "validation_sharpe": val_m.sharpe,
            "validation_sortino": val_m.sortino,
            "validation_total_return": val_m.total_return,
            "validation_gross_total_return": val_m.gross_total_return,
            "validation_cost_drag_return": val_m.cost_drag_return,
            "validation_cagr": val_m.cagr,
            "validation_max_drawdown": val_m.max_drawdown,
            "validation_annualized_volatility": val_m.annualized_volatility,
            "validation_turnover_daily": val_m.turnover_daily,
            "validation_trade_count": float(val_m.trade_count),
            "validation_hit_rate": val_m.hit_rate,
            "train_val_sharpe_gap": round(train_m.sharpe - val_m.sharpe, 10),
        }
        return BacktestResult(
            train_metrics=train_m,
            validation_metrics=val_m,
            train_returns=train_rets,
            validation_returns=val_rets,
            flat_metrics=flat_metrics,
            backtester_name=self.name,
            backtester_version=self.version,
        )


class TS14BacktesterAdapter:
    """Clean-room adapter boundary for Trading-Software project 14-ai-quant-research-agent.

    Per plan.md section 2, external personal repository code is not copied without confirmed
    licensing and SAAT ownership terms. By default this adapter delegates to the clean-room
    ReferenceBacktester while preserving the adapter seam for future vetted integration.
    """

    name = "ts14_clean_room_adapter"
    version = "1.0.0"

    def __init__(self, delegate: BacktesterAdapter | None = None, allow_external: bool = False) -> None:
        if allow_external:
            raise PolicyViolationError(
                "External TS-14 repository integration is disabled until IP/licensing review is approved"
            )
        self._delegate = delegate or ReferenceBacktester()

    def evaluate(
        self,
        spec: ExperimentSpec,
        train_bars: Dict[str, List[MarketBar]],
        validation_bars: Dict[str, List[MarketBar]],
    ) -> BacktestResult:
        res = self._delegate.evaluate(spec, train_bars, validation_bars)
        return BacktestResult(
            train_metrics=res.train_metrics,
            validation_metrics=res.validation_metrics,
            train_returns=res.train_returns,
            validation_returns=res.validation_returns,
            flat_metrics=res.flat_metrics,
            backtester_name=self.name,
            backtester_version=self.version,
        )

    def evaluate_single_split(
        self,
        hypothesis: HypothesisSpec,
        cost_model: CostModelSpec,
        bars_by_symbol: Dict[str, List[MarketBar]],
        split_name: str,
    ) -> tuple[SplitMetrics, List[float]]:
        return self._delegate.evaluate_single_split(hypothesis, cost_model, bars_by_symbol, split_name)
