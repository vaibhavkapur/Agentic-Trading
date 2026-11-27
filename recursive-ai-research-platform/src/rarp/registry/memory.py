"""Research memory, negative-result indexing, novelty checking, and trial accounting."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from rarp.domain.dsl import HypothesisSpec, StrategyCatalog
from rarp.domain.errors import DuplicateHypothesisError
from rarp.domain.types import RunStatus, utc_now_iso


@dataclass(frozen=True)
class TrialAccountingStats:
    total_trials: int
    succeeded_trials: int
    failed_or_rejected_trials: int
    observed_sharpe: float
    sample_bars: int
    expected_null_max_sharpe: float
    probabilistic_sharpe_ratio: float
    deflated_sharpe_ratio: float
    raw_two_sided_p_value: float
    bonferroni_p_value: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_trial_adjusted_stats(
    observed_sharpe: float,
    sample_bars: int,
    total_trials: int,
    succeeded_trials: int = 0,
    failed_or_rejected_trials: int = 0,
) -> TrialAccountingStats:
    """Compute PSR, Deflated Sharpe Ratio (DSR), and Bonferroni-adjusted p-value.

    Accounts for all attempted trials (including failed and rejected hypotheses) to
    mitigate multiple-testing / selection bias.
    """
    n_trials = max(1, total_trials)
    n_obs = max(2, sample_bars)

    # Standard error of annualized Sharpe approximation under IID normal assumption.
    # Daily SR = annualized_sr / sqrt(252); Var(SR_hat_daily) ~= (1 + 0.5*SR^2) / (n_obs - 1).
    daily_sr = observed_sharpe / math.sqrt(252.0)
    se_daily = math.sqrt((1.0 + 0.5 * daily_sr * daily_sr) / max(1, n_obs - 1))
    se_annual = max(1e-9, se_daily * math.sqrt(252.0))

    z_raw = observed_sharpe / se_annual
    psr = _norm_cdf(z_raw)
    raw_p = max(0.0, min(1.0, 2.0 * (1.0 - _norm_cdf(abs(z_raw)))))
    bonf_p = min(1.0, raw_p * n_trials)

    # Bailey & Lopez de Prado expected maximum Sharpe under null for N independent trials.
    if n_trials <= 1:
        e_max_z = 0.0
    else:
        euler_gamma = 0.5772156649
        e_max_z = math.sqrt(2.0 * math.log(n_trials)) - (
            (math.log(math.log(n_trials)) + math.log(4.0 * math.pi) - 2.0 * euler_gamma)
            / (2.0 * math.sqrt(2.0 * math.log(n_trials)))
        )
        e_max_z = max(0.0, e_max_z)
    null_max_sharpe = e_max_z * se_annual
    dsr = _norm_cdf((observed_sharpe - null_max_sharpe) / se_annual)

    return TrialAccountingStats(
        total_trials=n_trials,
        succeeded_trials=succeeded_trials,
        failed_or_rejected_trials=failed_or_rejected_trials,
        observed_sharpe=round(observed_sharpe, 8),
        sample_bars=n_obs,
        expected_null_max_sharpe=round(null_max_sharpe, 8),
        probabilistic_sharpe_ratio=round(psr, 8),
        deflated_sharpe_ratio=round(dsr, 8),
        raw_two_sided_p_value=round(raw_p, 8),
        bonferroni_p_value=round(bonf_p, 8),
    )


@dataclass(frozen=True)
class HypothesisMemoryEntry:
    hypothesis_id: str
    parent_hypothesis_id: Optional[str]
    generation: int
    title: str
    family: str
    parameters: Dict[str, Any]
    universe: List[str]
    fingerprint: str
    status: str
    run_id: Optional[str]
    validation_sharpe: Optional[float]
    critic_verdict: Optional[str]
    failure_reason: Optional[str]
    error_code: Optional[str]
    recorded_at_utc: str
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NoveltyCheckResult:
    is_novel: bool
    exact_duplicate_of: Optional[str] = None
    nearest_hypothesis_id: Optional[str] = None
    nearest_distance: Optional[float] = None


class ResearchMemory:
    """In-session and queryable research memory preserving both successes and negative results."""

    def __init__(self, catalog: StrategyCatalog, near_duplicate_distance: float = 0.03) -> None:
        self._catalog = catalog
        self._near_duplicate_distance = near_duplicate_distance
        self._entries: List[HypothesisMemoryEntry] = []
        self._by_fingerprint: Dict[str, HypothesisMemoryEntry] = {}

    def check_novelty(self, hypothesis: HypothesisSpec, raise_on_duplicate: bool = True) -> NoveltyCheckResult:
        fp = hypothesis.semantic_fingerprint()
        if fp in self._by_fingerprint:
            existing = self._by_fingerprint[fp]
            if raise_on_duplicate:
                raise DuplicateHypothesisError(
                    f"Exact duplicate hypothesis detected (matches {existing.hypothesis_id})",
                    {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "duplicate_of": existing.hypothesis_id,
                        "fingerprint": fp,
                        "is_near_duplicate": False,
                    },
                )
            return NoveltyCheckResult(
                is_novel=False,
                exact_duplicate_of=existing.hypothesis_id,
                nearest_hypothesis_id=existing.hypothesis_id,
                nearest_distance=0.0,
            )

        cand_norm = self._catalog.normalize_parameters(hypothesis.family, hypothesis.parameters)
        cand_universe = sorted(hypothesis.universe)
        nearest_id: Optional[str] = None
        nearest_dist: Optional[float] = None

        for entry in self._entries:
            if entry.family != hypothesis.family or sorted(entry.universe) != cand_universe:
                continue
            other_norm = self._catalog.normalize_parameters(entry.family, entry.parameters)
            keys = sorted(cand_norm.keys())
            dist = sum(abs(cand_norm[k] - other_norm[k]) for k in keys) / max(1, len(keys))
            if nearest_dist is None or dist < nearest_dist:
                nearest_dist = dist
                nearest_id = entry.hypothesis_id

        if nearest_dist is not None and nearest_dist < self._near_duplicate_distance:
            if raise_on_duplicate:
                raise DuplicateHypothesisError(
                    f"Near-duplicate hypothesis detected (distance={nearest_dist:.4f} < {self._near_duplicate_distance:.4f} to {nearest_id})",
                    {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "duplicate_of": nearest_id,
                        "distance": round(nearest_dist, 6),
                        "threshold": self._near_duplicate_distance,
                        "is_near_duplicate": True,
                    },
                )
            return NoveltyCheckResult(
                is_novel=False,
                exact_duplicate_of=None,
                nearest_hypothesis_id=nearest_id,
                nearest_distance=round(nearest_dist, 6),
            )

        return NoveltyCheckResult(
            is_novel=True,
            exact_duplicate_of=None,
            nearest_hypothesis_id=nearest_id,
            nearest_distance=round(nearest_dist, 6) if nearest_dist is not None else None,
        )

    def record(
        self,
        hypothesis: HypothesisSpec,
        status: RunStatus,
        run_id: Optional[str] = None,
        validation_sharpe: Optional[float] = None,
        critic_verdict: Optional[str] = None,
        failure_reason: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> HypothesisMemoryEntry:
        fp = hypothesis.semantic_fingerprint()
        entry = HypothesisMemoryEntry(
            hypothesis_id=hypothesis.hypothesis_id,
            parent_hypothesis_id=hypothesis.parent_hypothesis_id,
            generation=hypothesis.generation,
            title=hypothesis.title,
            family=hypothesis.family,
            parameters=dict(sorted(hypothesis.parameters.items())),
            universe=list(hypothesis.universe),
            fingerprint=fp,
            status=status.value,
            run_id=run_id,
            validation_sharpe=validation_sharpe,
            critic_verdict=critic_verdict,
            failure_reason=failure_reason,
            error_code=error_code,
            recorded_at_utc=utc_now_iso(),
            tags=list(hypothesis.tags),
        )
        self._entries.append(entry)
        self._by_fingerprint.setdefault(fp, entry)
        return entry

    def all_entries(self) -> List[HypothesisMemoryEntry]:
        return list(self._entries)

    def failed_hypotheses(
        self,
        family: Optional[str] = None,
        error_code: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[HypothesisMemoryEntry]:
        """Discover failed, rejected, or critic-rejected negative hypotheses."""
        results: List[HypothesisMemoryEntry] = []
        q = query.lower() if query else None
        for entry in self._entries:
            is_negative = (
                entry.status in (RunStatus.FAILED.value, RunStatus.REJECTED.value)
                or entry.critic_verdict == "REJECT"
            )
            if not is_negative:
                continue
            if family and entry.family != family:
                continue
            if error_code and entry.error_code != error_code:
                continue
            if q:
                haystack = f"{entry.hypothesis_id} {entry.title} {entry.family} {entry.failure_reason or ''}".lower()
                if q not in haystack:
                    continue
            results.append(entry)
        return results

    def trial_counts(self) -> Dict[str, int]:
        total = len(self._entries)
        succeeded = sum(1 for e in self._entries if e.status == RunStatus.SUCCEEDED.value)
        failed_or_rejected = total - succeeded
        return {
            "total_trials": total,
            "succeeded_trials": succeeded,
            "failed_or_rejected_trials": failed_or_rejected,
        }

    def best_entry(self) -> Optional[HypothesisMemoryEntry]:
        candidates = [
            e
            for e in self._entries
            if e.status == RunStatus.SUCCEEDED.value and e.validation_sharpe is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: float(e.validation_sharpe or -1e9))

    def trial_stats_for_sharpe(self, observed_sharpe: float, sample_bars: int) -> TrialAccountingStats:
        counts = self.trial_counts()
        return compute_trial_adjusted_stats(
            observed_sharpe=observed_sharpe,
            sample_bars=sample_bars,
            total_trials=max(1, counts["total_trials"]),
            succeeded_trials=counts["succeeded_trials"],
            failed_or_rejected_trials=counts["failed_or_rejected_trials"],
        )
