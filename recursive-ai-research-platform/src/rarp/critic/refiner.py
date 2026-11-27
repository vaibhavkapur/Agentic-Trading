"""Iterative bounded hypothesis refiner using research memory and critic findings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence

from rarp.critic.critic import CriticReport
from rarp.domain.dsl import HypothesisSpec, StrategyCatalog
from rarp.domain.errors import DuplicateHypothesisError, RARPValidationError
from rarp.domain.types import utc_now_iso
from rarp.registry.memory import ResearchMemory


class RefinerAdapter(Protocol):
    adapter_name: str

    def propose_next(
        self,
        parent: HypothesisSpec,
        critic_report: CriticReport,
        memory: ResearchMemory,
        catalog: StrategyCatalog,
        proposer_id: str,
        next_index: int,
    ) -> Optional[HypothesisSpec]:
        ...


def _clamp_int(val: int, lo: float, hi: float) -> int:
    return int(max(int(lo), min(int(hi), val)))


def _clamp_float(val: float, lo: float, hi: float) -> float:
    return round(max(float(lo), min(float(hi), val)), 4)


class DeterministicRefiner:
    """Bounded deterministic proposer that refines parameters using critic evidence and negative memory."""

    adapter_name = "deterministic_bounded_refiner_v1"

    def propose_initial_seed_hypotheses(
        self,
        universe: Sequence[str],
        proposer_id: str,
        catalog: StrategyCatalog,
    ) -> List[HypothesisSpec]:
        """Generate valid initial generation-0 hypotheses spanning catalog families."""
        now = utc_now_iso()
        candidates = [
            HypothesisSpec(
                hypothesis_id="hyp_0001_mom_base",
                title="Causal dual-MA momentum baseline (5/25)",
                rationale="Test medium-term trend continuation across synthetic multi-regime equities with 1-bar lag.",
                family="momentum_crossover",
                parameters={
                    "fast_window": 5,
                    "slow_window": 25,
                    "signal_lag_bars": 1,
                    "vol_target_annual": 0.15,
                },
                universe=tuple(universe),
                proposer_id=proposer_id,
                created_at_utc=now,
                parent_hypothesis_id=None,
                generation=0,
                tags=("baseline", "momentum"),
            ),
            HypothesisSpec(
                hypothesis_id="hyp_0002_mr_base",
                title="Causal rolling z-score mean reversion (20d)",
                rationale="Evaluate counter-trend mean reversion during choppy regimes with strict 1-bar lag.",
                family="mean_reversion_zscore",
                parameters={
                    "lookback_window": 20,
                    "entry_z": 1.5,
                    "exit_z": 0.25,
                    "signal_lag_bars": 1,
                },
                universe=tuple(universe),
                proposer_id=proposer_id,
                created_at_utc=now,
                parent_hypothesis_id=None,
                generation=0,
                tags=("baseline", "mean_reversion"),
            ),
            HypothesisSpec(
                hypothesis_id="hyp_0003_vol_breakout_base",
                title="Causal volatility-scaled channel breakout (15/20)",
                rationale="Test breakout sensitivity to volatility expansions across synthetic universe.",
                family="volatility_breakout",
                parameters={
                    "channel_window": 15,
                    "vol_window": 20,
                    "breakout_mult": 1.2,
                    "signal_lag_bars": 1,
                },
                universe=tuple(universe),
                proposer_id=proposer_id,
                created_at_utc=now,
                parent_hypothesis_id=None,
                generation=0,
                tags=("baseline", "breakout"),
            ),
        ]
        for h in candidates:
            h.validate(catalog)
        return candidates

    def propose_next(
        self,
        parent: HypothesisSpec,
        critic_report: CriticReport,
        memory: ResearchMemory,
        catalog: StrategyCatalog,
        proposer_id: str,
        next_index: int,
    ) -> Optional[HypothesisSpec]:
        """Generate a valid, novel refined hypothesis guided by critic findings."""
        finding_codes = {f.code for f in critic_report.findings}
        proposals: List[tuple[str, str, Dict[str, Any], str]] = []

        if parent.family == "momentum_crossover":
            fdef = catalog.families["momentum_crossover"].parameters
            p = parent.parameters
            # Candidate mutations prioritized by critic feedback.
            deltas = []
            if "HIGH_COST_DRAG" in finding_codes or "OVERFIT_DEGRADATION" in finding_codes:
                deltas.extend([(3, 15, 0, -0.02), (5, 25, 1, -0.03)])
            if "EXCESSIVE_DRAWDOWN" in finding_codes:
                deltas.extend([(2, 10, 0, -0.05), (4, 20, 0, -0.05)])
            if "LOW_SAMPLE_TRADES" in finding_codes:
                deltas.extend([(-2, -10, 0, 0.0), (-1, -5, 0, 0.0)])
            deltas.extend(
                [
                    (3, 15, 0, 0.0),
                    (5, 25, 0, 0.03),
                    (-2, 10, 0, -0.02),
                    (7, 35, 1, 0.02),
                    (10, 40, 0, -0.04),
                ]
            )
            for df, ds, dlag, dvol in deltas:
                fast = _clamp_int(int(p["fast_window"]) + df, fdef["fast_window"].min_value, fdef["fast_window"].max_value)
                slow = _clamp_int(int(p["slow_window"]) + ds, fdef["slow_window"].min_value, fdef["slow_window"].max_value)
                if fast >= slow:
                    slow = _clamp_int(fast + 5, fdef["slow_window"].min_value, fdef["slow_window"].max_value)
                lag = _clamp_int(int(p["signal_lag_bars"]) + dlag, fdef["signal_lag_bars"].min_value, fdef["signal_lag_bars"].max_value)
                vol = _clamp_float(float(p["vol_target_annual"]) + dvol, fdef["vol_target_annual"].min_value, fdef["vol_target_annual"].max_value)
                proposals.append(
                    (
                        "momentum_crossover",
                        f"Refined momentum ({fast}/{slow}, lag={lag}, vol={vol:.2f})",
                        {
                            "fast_window": fast,
                            "slow_window": slow,
                            "signal_lag_bars": lag,
                            "vol_target_annual": vol,
                        },
                        f"Adjusted from {parent.hypothesis_id} addressing critic codes {sorted(finding_codes) or ['GENERAL_TUNING']}.",
                    )
                )

        elif parent.family == "mean_reversion_zscore":
            fdef = catalog.families["mean_reversion_zscore"].parameters
            p = parent.parameters
            deltas = [
                (10, 0.3, 0.0, 0),
                (-5, -0.25, 0.0, 0),
                (15, 0.5, 0.1, 1),
                (5, 0.2, -0.1, 0),
            ]
            for dlb, dez, dxz, dlag in deltas:
                lb = _clamp_int(int(p["lookback_window"]) + dlb, fdef["lookback_window"].min_value, fdef["lookback_window"].max_value)
                ez = _clamp_float(float(p["entry_z"]) + dez, fdef["entry_z"].min_value, fdef["entry_z"].max_value)
                xz = _clamp_float(float(p["exit_z"]) + dxz, fdef["exit_z"].min_value, fdef["exit_z"].max_value)
                if xz >= ez:
                    xz = round(max(0.0, ez - 0.5), 4)
                lag = _clamp_int(int(p["signal_lag_bars"]) + dlag, fdef["signal_lag_bars"].min_value, fdef["signal_lag_bars"].max_value)
                proposals.append(
                    (
                        "mean_reversion_zscore",
                        f"Refined mean-reversion (lb={lb}, ez={ez:.2f}, xz={xz:.2f})",
                        {
                            "lookback_window": lb,
                            "entry_z": ez,
                            "exit_z": xz,
                            "signal_lag_bars": lag,
                        },
                        f"Adjusted from {parent.hypothesis_id} addressing critic codes {sorted(finding_codes) or ['GENERAL_TUNING']}.",
                    )
                )

        elif parent.family == "volatility_breakout":
            fdef = catalog.families["volatility_breakout"].parameters
            p = parent.parameters
            deltas = [
                (5, 5, 0.3, 0),
                (-5, 0, -0.2, 0),
                (10, 10, 0.5, 1),
                (15, -5, 0.4, 0),
            ]
            for dch, dv, dm, dlag in deltas:
                ch = _clamp_int(int(p["channel_window"]) + dch, fdef["channel_window"].min_value, fdef["channel_window"].max_value)
                vw = _clamp_int(int(p["vol_window"]) + dv, fdef["vol_window"].min_value, fdef["vol_window"].max_value)
                bm = _clamp_float(float(p["breakout_mult"]) + dm, fdef["breakout_mult"].min_value, fdef["breakout_mult"].max_value)
                lag = _clamp_int(int(p["signal_lag_bars"]) + dlag, fdef["signal_lag_bars"].min_value, fdef["signal_lag_bars"].max_value)
                proposals.append(
                    (
                        "volatility_breakout",
                        f"Refined vol breakout (ch={ch}, vol={vw}, mult={bm:.2f})",
                        {
                            "channel_window": ch,
                            "vol_window": vw,
                            "breakout_mult": bm,
                            "signal_lag_bars": lag,
                        },
                        f"Adjusted from {parent.hypothesis_id} addressing critic codes {sorted(finding_codes) or ['GENERAL_TUNING']}.",
                    )
                )

        # Fallback cross-family exploration if local mutations are exhausted.
        proposals.append(
            (
                "momentum_crossover",
                "Cross-family momentum exploration (8/40)",
                {
                    "fast_window": 8,
                    "slow_window": 40,
                    "signal_lag_bars": 1,
                    "vol_target_annual": 0.18,
                },
                "Fallback exploration after exhausting local parameter neighborhood.",
            )
        )

        now = utc_now_iso()
        for family, title, params, rationale in proposals:
            cand = HypothesisSpec(
                hypothesis_id=f"hyp_{next_index:04d}_gen{parent.generation + 1}",
                title=title,
                rationale=rationale,
                family=family,
                parameters=params,
                universe=parent.universe,
                proposer_id=proposer_id,
                created_at_utc=now,
                parent_hypothesis_id=parent.hypothesis_id,
                generation=parent.generation + 1,
                tags=("refined", f"gen_{parent.generation + 1}"),
            )
            try:
                cand.validate(catalog)
                memory.check_novelty(cand, raise_on_duplicate=True)
                return cand
            except (RARPValidationError, DuplicateHypothesisError):
                continue

        return None


class HypothesisRefiner:
    """High-level wrapper validating all refiner outputs against DSL and novelty policy."""

    def __init__(self, catalog: StrategyCatalog, adapter: Optional[RefinerAdapter] = None) -> None:
        self._catalog = catalog
        self._adapter: RefinerAdapter = adapter or DeterministicRefiner()

    def propose_next(
        self,
        parent: HypothesisSpec,
        critic_report: CriticReport,
        memory: ResearchMemory,
        proposer_id: str,
        next_index: int,
    ) -> Optional[HypothesisSpec]:
        proposal = self._adapter.propose_next(
            parent=parent,
            critic_report=critic_report,
            memory=memory,
            catalog=self._catalog,
            proposer_id=proposer_id,
            next_index=next_index,
        )
        if proposal is None:
            return None
        proposal.validate(self._catalog)
        memory.check_novelty(proposal, raise_on_duplicate=True)
        return proposal
