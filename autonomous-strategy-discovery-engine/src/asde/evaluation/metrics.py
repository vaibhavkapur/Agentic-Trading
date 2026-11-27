"""Performance, risk, drawdown, turnover, and bootstrap uncertainty metrics."""

from __future__ import annotations

import math
import random
from typing import List, Tuple

from asde.types import EvaluationMetrics


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(max(var, 0.0))


def _moments(xs: List[float]) -> Tuple[float, float]:
    """Return sample skewness and Pearson kurtosis (normal == 3.0)."""
    n = len(xs)
    if n < 4:
        return 0.0, 3.0
    m = _mean(xs)
    s = _std(xs)
    if s <= 1e-12:
        return 0.0, 3.0
    z = [(x - m) / s for x in xs]
    skew = sum(v ** 3 for v in z) / n
    kurt = sum(v ** 4 for v in z) / n
    return skew, kurt


def _compound_return(rets: List[float]) -> float:
    eq = 1.0
    for r in rets:
        eq *= max(1e-9, 1.0 + r)
    return eq - 1.0


def _max_drawdown(rets: List[float]) -> float:
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        eq *= max(1e-9, 1.0 + r)
        if eq > peak:
            peak = eq
        dd = 1.0 - (eq / peak)
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _annualized_sharpe(rets: List[float], rf_per_bar: float, ann: int) -> float:
    if len(rets) < 2:
        return 0.0
    excess = [r - rf_per_bar for r in rets]
    sd = _std(excess)
    if sd <= 1e-12:
        return 0.0
    return (_mean(excess) / sd) * math.sqrt(float(ann))


def _cagr(rets: List[float], ann: int) -> float:
    n = len(rets)
    if n == 0:
        return 0.0
    tot = _compound_return(rets)
    if 1.0 + tot <= 1e-9:
        return -1.0
    years = n / float(ann)
    return (1.0 + tot) ** (1.0 / max(years, 1e-6)) - 1.0


def _block_bootstrap_ci(
    rets: List[float],
    *,
    rf_per_bar: float,
    ann: int,
    num_samples: int,
    block_size: int,
    seed: int,
) -> Tuple[float, float, float, float]:
    """Moving-block bootstrap 95% confidence intervals for Sharpe and CAGR."""
    n = len(rets)
    if n < 5 or num_samples <= 0:
        sr = _annualized_sharpe(rets, rf_per_bar, ann)
        cg = _cagr(rets, ann)
        return sr, sr, cg, cg

    rng = random.Random(seed)
    blk = max(1, min(block_size, n))
    sharpes: List[float] = []
    cagrs: List[float] = []
    max_start = max(0, n - blk)
    for _ in range(num_samples):
        sample: List[float] = []
        while len(sample) < n:
            st = rng.randint(0, max_start) if max_start > 0 else 0
            sample.extend(rets[st : st + blk])
        sample = sample[:n]
        sharpes.append(_annualized_sharpe(sample, rf_per_bar, ann))
        cagrs.append(_cagr(sample, ann))

    sharpes.sort()
    cagrs.sort()
    lo_idx = max(0, int(0.025 * len(sharpes)))
    hi_idx = min(len(sharpes) - 1, int(0.975 * len(sharpes)))
    return sharpes[lo_idx], sharpes[hi_idx], cagrs[lo_idx], cagrs[hi_idx]


def compute_metrics(
    *,
    net_returns: List[float],
    gross_returns: List[float],
    turnovers: List[float],
    cost_drags: List[float],
    annualization_factor: int = 252,
    risk_free_rate_annual: float = 0.02,
    bootstrap_samples: int = 200,
    bootstrap_block_size: int = 10,
    seed: int = 42,
) -> EvaluationMetrics:
    """Compute comprehensive performance, cost, drawdown, turnover, and uncertainty metrics."""
    n = len(net_returns)
    rf_bar = risk_free_rate_annual / float(annualization_factor)
    tot_ret = _compound_return(net_returns)
    gross_tot_ret = _compound_return(gross_returns)
    cagr = _cagr(net_returns, annualization_factor)
    ann_vol = _std(net_returns) * math.sqrt(float(annualization_factor))
    sharpe = _annualized_sharpe(net_returns, rf_bar, annualization_factor)
    gross_sharpe = _annualized_sharpe(gross_returns, rf_bar, annualization_factor)

    downside = [min(0.0, r - rf_bar) for r in net_returns]
    downside_dev = math.sqrt(sum(d * d for d in downside) / max(n, 1)) * math.sqrt(float(annualization_factor))
    sortino = ((_mean(net_returns) - rf_bar) * annualization_factor / downside_dev) if downside_dev > 1e-12 else 0.0

    max_dd = _max_drawdown(net_returns)
    calmar = (cagr / max_dd) if max_dd > 1e-9 else 0.0

    # Annualized two-sided traded notional / NAV
    ann_turnover = (_mean(turnovers) * float(annualization_factor)) if turnovers else 0.0
    total_cost_drag = sum(cost_drags)

    gains = sum(r for r in net_returns if r > 0.0)
    losses = abs(sum(r for r in net_returns if r < 0.0))
    win_rate = (sum(1 for r in net_returns if r > 0.0) / float(n)) if n > 0 else 0.0
    profit_factor = (gains / losses) if losses > 1e-12 else (99.0 if gains > 0 else 0.0)

    skew, kurt = _moments(net_returns)

    # Mertens (2002) non-normal standard error of annualized Sharpe
    if n > 2:
        sr_bar = sharpe / math.sqrt(float(annualization_factor))
        se_bar = math.sqrt(
            max(1e-12, (1.0 - skew * sr_bar + ((kurt - 1.0) / 4.0) * (sr_bar ** 2)) / float(n - 1))
        )
        sharpe_se = se_bar * math.sqrt(float(annualization_factor))
    else:
        sharpe_se = 0.0

    sr_lo, sr_hi, cagr_lo, cagr_hi = _block_bootstrap_ci(
        net_returns,
        rf_per_bar=rf_bar,
        ann=annualization_factor,
        num_samples=bootstrap_samples,
        block_size=bootstrap_block_size,
        seed=seed,
    )

    return EvaluationMetrics(
        total_return=round(tot_ret, 6),
        cagr=round(cagr, 6),
        annualized_volatility=round(ann_vol, 6),
        sharpe_ratio=round(sharpe, 6),
        sortino_ratio=round(sortino, 6),
        max_drawdown=round(max_dd, 6),
        calmar_ratio=round(calmar, 6),
        annualized_turnover=round(ann_turnover, 6),
        total_cost_drag=round(total_cost_drag, 6),
        gross_total_return=round(gross_tot_ret, 6),
        gross_sharpe_ratio=round(gross_sharpe, 6),
        win_rate=round(win_rate, 6),
        profit_factor=round(min(profit_factor, 99.0), 6),
        num_bars=n,
        sharpe_se=round(sharpe_se, 6),
        sharpe_ci_low=round(sr_lo, 6),
        sharpe_ci_high=round(sr_hi, 6),
        cagr_ci_low=round(cagr_lo, 6),
        cagr_ci_high=round(cagr_hi, 6),
        skewness=round(skew, 6),
        kurtosis=round(kurt, 6),
    )
