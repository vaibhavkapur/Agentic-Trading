"""Multiple-testing adjustments: PSR, Deflated Sharpe Ratio (DSR), Bonferroni, Holm, and BH-FDR."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any, Dict, List


_EULER_MASCHERONI = 0.5772156649015329


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Accurate Acklam rational approximation to the inverse standard normal CDF."""
    p = min(max(p, 1e-12), 1.0 - 1e-12)
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


def probabilistic_sharpe_ratio(
    *,
    sharpe_annual: float,
    benchmark_sharpe_annual: float,
    num_bars: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    annualization_factor: int = 252,
) -> float:
    """Bailey & Lopez de Prado (2012) Probabilistic Sharpe Ratio (PSR)."""
    if num_bars < 3:
        return 0.5
    scale = math.sqrt(float(annualization_factor))
    sr = sharpe_annual / scale
    sr0 = benchmark_sharpe_annual / scale
    denom_sq = 1.0 - skewness * sr + ((kurtosis - 1.0) / 4.0) * (sr ** 2)
    denom = math.sqrt(max(denom_sq, 1e-12))
    z = (sr - sr0) * math.sqrt(float(num_bars - 1)) / denom
    return norm_cdf(z)


def expected_max_sharpe(num_trials: int, sharpe_std_annual: float) -> float:
    """Expected maximum Sharpe under the null across N independent trials (False Strategy Theorem)."""
    if num_trials <= 1 or sharpe_std_annual <= 0.0:
        return 0.0
    n = float(num_trials)
    z1 = norm_ppf(1.0 - 1.0 / n)
    z2 = norm_ppf(1.0 - 1.0 / (n * math.e))
    return sharpe_std_annual * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def deflated_sharpe_ratio(
    *,
    sharpe_annual: float,
    num_bars: int,
    total_trials_n: int,
    trial_sharpe_std_annual: float,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    annualization_factor: int = 252,
) -> Dict[str, float]:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio (DSR)."""
    sr_star = expected_max_sharpe(max(1, total_trials_n), max(trial_sharpe_std_annual, 0.25))
    dsr_prob = probabilistic_sharpe_ratio(
        sharpe_annual=sharpe_annual,
        benchmark_sharpe_annual=sr_star,
        num_bars=num_bars,
        skewness=skewness,
        kurtosis=kurtosis,
        annualization_factor=annualization_factor,
    )
    return {
        "expected_max_null_sharpe": round(sr_star, 6),
        "dsr_probability": round(dsr_prob, 6),
    }


@dataclass
class MultipleTestingStats:
    strategy_id: str
    total_trials_accounted: int
    raw_sharpe: float
    raw_p_value: float
    psr_vs_zero: float
    expected_max_null_sharpe: float
    dsr_probability: float
    bonferroni_p_value: float
    holm_p_value: float
    bh_fdr_q_value: float
    passes_fdr: bool
    passes_dsr: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_multiple_testing(
    *,
    candidate_entries: List[Dict[str, Any]],
    total_trials_accounted: int,
    fdr_alpha: float = 0.10,
    min_dsr_prob: float = 0.50,
    annualization_factor: int = 252,
) -> Dict[str, MultipleTestingStats]:
    """Compute PSR, DSR, Bonferroni, Holm-Bonferroni, and Benjamini-Hochberg FDR across ALL trials.

    Crucially, `total_trials_accounted` includes failed, rejected, and inner-tuning trials so
    dropping poor experiments never hides multiple-testing inflation.
    """
    n_total = max(1, total_trials_accounted, len(candidate_entries))
    # Under H0: SR_k = 0 for all k=1..N, the annualized sampling standard deviation is sqrt(ann / T).
    # Using the theoretical null sampling dispersion prevents adding terrible/inverted strategy families
    # from artificially inflating V0[SR] and masking genuine out-of-sample strategies, while remaining
    # strictly calibrated under pure-noise multiple-testing inflation.
    avg_bars = (
        sum(int(e.get("num_bars", 252)) for e in candidate_entries) / float(len(candidate_entries))
        if candidate_entries
        else 252.0
    )
    eff_std = math.sqrt(float(annualization_factor) / max(avg_bars, 20.0))

    raw_items: List[Dict[str, Any]] = []
    for e in candidate_entries:
        sid = e["strategy_id"]
        sr = float(e["sharpe_ratio"])
        num_bars = int(e.get("num_bars", 252))
        skew = float(e.get("skewness", 0.0))
        kurt = float(e.get("kurtosis", 3.0))
        psr = probabilistic_sharpe_ratio(
            sharpe_annual=sr,
            benchmark_sharpe_annual=0.0,
            num_bars=num_bars,
            skewness=skew,
            kurtosis=kurt,
            annualization_factor=annualization_factor,
        )
        raw_p = max(1e-12, min(1.0, 1.0 - psr))
        dsr_info = deflated_sharpe_ratio(
            sharpe_annual=sr,
            num_bars=num_bars,
            total_trials_n=n_total,
            trial_sharpe_std_annual=eff_std,
            skewness=skew,
            kurtosis=kurt,
            annualization_factor=annualization_factor,
        )
        raw_items.append(
            {
                "strategy_id": sid,
                "sharpe": sr,
                "raw_p": raw_p,
                "psr": psr,
                "sr_star": dsr_info["expected_max_null_sharpe"],
                "dsr": dsr_info["dsr_probability"],
            }
        )

    # Sort ascending by raw p-value for Holm and Benjamini-Hochberg using full n_total
    raw_items.sort(key=lambda x: (x["raw_p"], x["strategy_id"]))
    m_eval = len(raw_items)
    holm_vals = [0.0] * m_eval
    running_max = 0.0
    for rank_idx, item in enumerate(raw_items):
        adj = min(1.0, item["raw_p"] * float(max(1, n_total - rank_idx)))
        running_max = max(running_max, adj)
        holm_vals[rank_idx] = running_max

    bh_vals = [1.0] * m_eval
    running_min = 1.0
    for rank_idx in range(m_eval - 1, -1, -1):
        rank = rank_idx + 1
        q = min(1.0, raw_items[rank_idx]["raw_p"] * float(n_total) / float(rank))
        running_min = min(running_min, q)
        bh_vals[rank_idx] = running_min

    results: Dict[str, MultipleTestingStats] = {}
    for idx, item in enumerate(raw_items):
        bonf = min(1.0, item["raw_p"] * float(n_total))
        holm = holm_vals[idx]
        bh_q = bh_vals[idx]
        results[item["strategy_id"]] = MultipleTestingStats(
            strategy_id=item["strategy_id"],
            total_trials_accounted=n_total,
            raw_sharpe=round(item["sharpe"], 6),
            raw_p_value=round(item["raw_p"], 6),
            psr_vs_zero=round(item["psr"], 6),
            expected_max_null_sharpe=round(item["sr_star"], 6),
            dsr_probability=round(item["dsr"], 6),
            bonferroni_p_value=round(bonf, 6),
            holm_p_value=round(holm, 6),
            bh_fdr_q_value=round(bh_q, 6),
            passes_fdr=bh_q <= fdr_alpha,
            passes_dsr=item["dsr"] >= min_dsr_prob,
        )
    return results
