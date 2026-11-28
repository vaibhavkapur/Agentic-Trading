"""Pure statistical utilities for confidence intervals, percentiles, and baseline diffs.

Zero external numerical dependencies required; deterministic and fully testable.
"""

from __future__ import annotations

import math
import random
from typing import Sequence

from fin_eval.schemas import BaselineComparison, ConfidenceInterval, EvaluationReport

# Two-tailed 95% Student-t critical values by degrees of freedom (df = 1..30)
_T_CRIT_95: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def wilson_interval(successes: int, n: int, confidence_level: float = 0.95) -> ConfidenceInterval:
    """Compute a Wilson score confidence interval for a binomial proportion."""
    if n <= 0:
        raise ValueError("n must be >= 1")
    if successes < 0 or successes > n:
        raise ValueError("successes must be in [0, n]")

    z = 1.959963984540054 if math.isclose(confidence_level, 0.95, rel_tol=1e-6) else 1.6448536269514722
    p = successes / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half_width = (z / denom) * math.sqrt((p * (1.0 - p)) / n + (z * z) / (4.0 * n * n))

    std_dev = math.sqrt(p * (1.0 - p))
    return ConfidenceInterval(
        mean=round(p, 6),
        lower=round(max(0.0, center - half_width), 6),
        upper=round(min(1.0, center + half_width), 6),
        confidence_level=confidence_level,
        method="wilson",
        n_samples=n,
        std_dev=round(std_dev, 6),
    )


def t_confidence_interval(
    values: Sequence[float],
    confidence_level: float = 0.95,
    clamp_unit: bool = True,
) -> ConfidenceInterval:
    """Compute a Student-t confidence interval for continuous sample values."""
    n = len(values)
    if n == 0:
        raise ValueError("values must be non-empty")

    mean = sum(values) / n
    if n == 1:
        return ConfidenceInterval(
            mean=round(mean, 6),
            lower=round(mean, 6),
            upper=round(mean, 6),
            confidence_level=confidence_level,
            method="exact_single",
            n_samples=1,
            std_dev=0.0,
        )

    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std_dev = math.sqrt(variance)
    df = n - 1
    t_crit = _T_CRIT_95.get(df, 1.96)
    margin = t_crit * (std_dev / math.sqrt(n))

    lower = mean - margin
    upper = mean + margin
    if clamp_unit:
        lower = max(0.0, lower)
        upper = min(1.0, upper)

    return ConfidenceInterval(
        mean=round(mean, 6),
        lower=round(lower, 6),
        upper=round(upper, 6),
        confidence_level=confidence_level,
        method="t_interval",
        n_samples=n,
        std_dev=round(std_dev, 6),
    )


def bootstrap_confidence_interval(
    values: Sequence[float],
    seed: int = 42,
    n_resamples: int = 500,
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    """Deterministic seeded percentile bootstrap confidence interval."""
    n = len(values)
    if n == 0:
        raise ValueError("values must be non-empty")
    mean = sum(values) / n
    if n == 1:
        return ConfidenceInterval(
            mean=round(mean, 6),
            lower=round(mean, 6),
            upper=round(mean, 6),
            confidence_level=confidence_level,
            method="exact_single",
            n_samples=1,
            std_dev=0.0,
        )

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = (1.0 - confidence_level) / 2.0
    low_idx = max(0, min(n_resamples - 1, int(alpha * n_resamples)))
    high_idx = max(0, min(n_resamples - 1, int((1.0 - alpha) * n_resamples) - 1))
    std_dev = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))

    return ConfidenceInterval(
        mean=round(mean, 6),
        lower=round(means[low_idx], 6),
        upper=round(means[high_idx], 6),
        confidence_level=confidence_level,
        method="bootstrap",
        n_samples=n,
        std_dev=round(std_dev, 6),
    )


def percentile(values: Sequence[float], p: float) -> float:
    """Compute linear-interpolated percentile p in [0, 100]."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 6)
    rank = (p / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return round(sorted_vals[lo], 6)
    frac = rank - lo
    return round(sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo]), 6)


def compare_reports(
    current: EvaluationReport,
    baseline: EvaluationReport,
    tolerance: float = 0.02,
) -> BaselineComparison:
    """Compare a current EvaluationReport against a baseline report within tolerance."""
    pass_delta = round(current.summary.pass_rate.mean - baseline.summary.pass_rate.mean, 6)
    score_delta = round(current.summary.mean_score.mean - baseline.summary.mean_score.mean, 6)

    baseline_by_task: dict[str, list[float]] = {}
    for res in baseline.task_results:
        baseline_by_task.setdefault(res.task_id, []).append(res.overall_score)

    current_by_task: dict[str, list[float]] = {}
    for res in current.task_results:
        current_by_task.setdefault(res.task_id, []).append(res.overall_score)

    regressions: list[str] = []
    improvements: list[str] = []

    for task_id in sorted(set(baseline_by_task).intersection(current_by_task)):
        b_mean = sum(baseline_by_task[task_id]) / len(baseline_by_task[task_id])
        c_mean = sum(current_by_task[task_id]) / len(current_by_task[task_id])
        diff = c_mean - b_mean
        if diff < -tolerance:
            regressions.append(f"{task_id}: {b_mean:.3f} -> {c_mean:.3f} ({diff:+.3f})")
        elif diff > tolerance:
            improvements.append(f"{task_id}: {b_mean:.3f} -> {c_mean:.3f} ({diff:+.3f})")

    within_tolerance = (
        pass_delta >= -tolerance
        and score_delta >= -tolerance
        and len(regressions) == 0
    )

    notes = (
        "Within baseline tolerance."
        if within_tolerance
        else f"Deviation exceeds tolerance {tolerance:.3f}: {len(regressions)} task regression(s)."
    )

    return BaselineComparison(
        baseline_report_id=baseline.report_id,
        pass_rate_delta=pass_delta,
        mean_score_delta=score_delta,
        tolerance=tolerance,
        within_tolerance=within_tolerance,
        regressions=regressions,
        improvements=improvements,
        notes=notes,
    )
