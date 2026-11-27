"""Evidence-linked critic that cryptographically binds every metric claim to immutable runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Protocol

from rarp.domain.errors import HallucinatedMetricError
from rarp.domain.types import sha256_json, utc_now_iso
from rarp.registry.memory import TrialAccountingStats
from rarp.registry.store import RunRecord, RunRegistry


@dataclass(frozen=True)
class CriticConfig:
    metric_tolerance: float = 1e-9
    min_trade_count: int = 5
    max_drawdown_limit: float = 0.35
    min_validation_sharpe: float = 0.20
    max_train_val_sharpe_gap: float = 1.50


@dataclass(frozen=True)
class MetricClaim:
    run_id: str
    metric_name: str
    claimed_value: float
    artifact_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CriticFinding:
    code: str
    severity: str
    message: str
    evidence_metrics: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CriticReport:
    report_id: str
    run_id: str
    hypothesis_id: str
    verdict: str  # "CANDIDATE_FOR_REVIEW", "REFINE", "REJECT"
    summary: str
    findings: List[CriticFinding]
    claims: List[MetricClaim]
    trial_accounting: Dict[str, Any]
    verified: bool
    critic_adapter: str
    created_at_utc: str
    report_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "hypothesis_id": self.hypothesis_id,
            "verdict": self.verdict,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "claims": [c.to_dict() for c in self.claims],
            "trial_accounting": self.trial_accounting,
            "verified": self.verified,
            "critic_adapter": self.critic_adapter,
            "created_at_utc": self.created_at_utc,
            "report_sha256": self.report_sha256,
        }


class CriticAdapter(Protocol):
    """Optional external LLM or deterministic critic backend producing raw unverified drafts."""

    adapter_name: str

    def draft_critique(
        self,
        run: RunRecord,
        trial_stats: TrialAccountingStats,
        config: CriticConfig,
    ) -> Dict[str, Any]:
        ...


class DeterministicCriticAdapter:
    """Zero-dependency deterministic critic that links every assessment to recorded run metrics."""

    adapter_name = "deterministic_evidence_critic_v1"

    def draft_critique(
        self,
        run: RunRecord,
        trial_stats: TrialAccountingStats,
        config: CriticConfig,
    ) -> Dict[str, Any]:
        m = run.metrics
        required_keys = [
            "train_sharpe",
            "validation_sharpe",
            "validation_max_drawdown",
            "validation_trade_count",
            "validation_cost_drag_return",
            "train_val_sharpe_gap",
        ]
        claims = [
            MetricClaim(
                run_id=run.run_id,
                metric_name=key,
                claimed_value=float(m[key]),
                artifact_sha256=run.artifact_sha256,
            )
            for key in required_keys
            if key in m
        ]

        findings: List[CriticFinding] = []
        hard_failures = 0
        soft_warnings = 0

        val_sharpe = float(m.get("validation_sharpe", 0.0))
        val_dd = float(m.get("validation_max_drawdown", 1.0))
        val_trades = int(m.get("validation_trade_count", 0))
        sharpe_gap = float(m.get("train_val_sharpe_gap", 0.0))
        cost_drag = float(m.get("validation_cost_drag_return", 0.0))

        if val_trades < config.min_trade_count:
            hard_failures += 1
            findings.append(
                CriticFinding(
                    code="LOW_SAMPLE_TRADES",
                    severity="ERROR",
                    message=f"Validation trade count ({val_trades}) is below minimum ({config.min_trade_count}).",
                    evidence_metrics=["validation_trade_count"],
                )
            )
        if val_dd > config.max_drawdown_limit:
            hard_failures += 1
            findings.append(
                CriticFinding(
                    code="EXCESSIVE_DRAWDOWN",
                    severity="ERROR",
                    message=f"Validation max drawdown ({val_dd:.2%}) exceeds limit ({config.max_drawdown_limit:.2%}).",
                    evidence_metrics=["validation_max_drawdown"],
                )
            )
        if sharpe_gap > config.max_train_val_sharpe_gap:
            soft_warnings += 1
            findings.append(
                CriticFinding(
                    code="OVERFIT_DEGRADATION",
                    severity="WARNING",
                    message=f"Train-to-validation Sharpe degradation ({sharpe_gap:.3f}) exceeds threshold ({config.max_train_val_sharpe_gap:.3f}).",
                    evidence_metrics=["train_sharpe", "validation_sharpe", "train_val_sharpe_gap"],
                )
            )
        if val_sharpe < config.min_validation_sharpe:
            soft_warnings += 1
            findings.append(
                CriticFinding(
                    code="WEAK_VALIDATION_SHARPE",
                    severity="WARNING",
                    message=f"Validation Sharpe ({val_sharpe:.3f}) is below target ({config.min_validation_sharpe:.3f}).",
                    evidence_metrics=["validation_sharpe"],
                )
            )
        if cost_drag > 0.03:
            soft_warnings += 1
            findings.append(
                CriticFinding(
                    code="HIGH_COST_DRAG",
                    severity="WARNING",
                    message=f"Transaction cost drag ({cost_drag:.2%}) materially erodes gross validation return.",
                    evidence_metrics=["validation_cost_drag_return"],
                )
            )
        if trial_stats.deflated_sharpe_ratio < 0.50:
            soft_warnings += 1
            findings.append(
                CriticFinding(
                    code="MULTIPLE_TESTING_CAUTION",
                    severity="INFO",
                    message=(
                        f"Deflated Sharpe Ratio ({trial_stats.deflated_sharpe_ratio:.3f}) across "
                        f"{trial_stats.total_trials} trials indicates selection-bias risk; do not infer live alpha."
                    ),
                    evidence_metrics=["validation_sharpe"],
                )
            )

        if hard_failures > 0:
            verdict = "REJECT"
        elif val_sharpe >= config.min_validation_sharpe and sharpe_gap <= config.max_train_val_sharpe_gap:
            verdict = "CANDIDATE_FOR_REVIEW"
        else:
            verdict = "REFINE"

        summary = (
            f"Run {run.run_id} verdict={verdict}: val_sharpe={val_sharpe:.3f}, "
            f"max_dd={val_dd:.2%}, trades={val_trades}, DSR={trial_stats.deflated_sharpe_ratio:.3f} "
            f"(N={trial_stats.total_trials} trials)."
        )
        return {
            "verdict": verdict,
            "summary": summary,
            "findings": findings,
            "claims": claims,
        }


class ResearchCritic:
    """Verifies all critic claims against the immutable RunRegistry before accepting a report."""

    def __init__(
        self,
        registry: RunRegistry,
        config: Optional[CriticConfig] = None,
        adapter: Optional[CriticAdapter] = None,
    ) -> None:
        self._registry = registry
        self._config = config or CriticConfig()
        self._adapter: CriticAdapter = adapter or DeterministicCriticAdapter()

    def verify_claims(self, claims: List[MetricClaim]) -> None:
        """Strictly validate every MetricClaim against immutable registry records.

        Raises HallucinatedMetricError if any claim cites a missing run, forged artifact hash,
        unknown metric key, or value differing beyond configured tolerance.
        """
        if not claims:
            raise HallucinatedMetricError(
                "Critic report contains zero evidence-linked metric claims",
                {"reason": "empty_claims"},
            )

        for claim in claims:
            run = self._registry.get_run(claim.run_id)
            if run is None:
                self._quarantine_hallucination(claim, "Referenced run_id does not exist in immutable registry")
            if claim.artifact_sha256 != run.artifact_sha256:
                self._quarantine_hallucination(
                    claim,
                    f"Artifact SHA-256 mismatch (claimed={claim.artifact_sha256}, actual={run.artifact_sha256})",
                )
            if claim.metric_name not in run.metrics:
                self._quarantine_hallucination(
                    claim,
                    f"Metric '{claim.metric_name}' does not exist in run {claim.run_id}",
                )
            actual = float(run.metrics[claim.metric_name])
            diff = abs(float(claim.claimed_value) - actual)
            if diff > self._config.metric_tolerance:
                self._quarantine_hallucination(
                    claim,
                    f"Metric '{claim.metric_name}' value mismatch: claimed={claim.claimed_value}, "
                    f"actual={actual}, diff={diff:.3e} > tol={self._config.metric_tolerance:.3e}",
                )

    def _quarantine_hallucination(self, claim: MetricClaim, reason: str) -> None:
        self._registry.record_audit_event(
            event_type="HALLUCINATED_METRIC_DETECTED",
            actor_id="research_critic_verifier",
            details={"claim": claim.to_dict(), "reason": reason},
        )
        raise HallucinatedMetricError(
            f"Hallucinated or unverified metric claim rejected: {reason}",
            {"claim": claim.to_dict(), "reason": reason},
        )

    def evaluate_run(
        self,
        run: RunRecord,
        trial_stats: TrialAccountingStats,
        adapter_override: Optional[CriticAdapter] = None,
    ) -> CriticReport:
        adapter = adapter_override or self._adapter
        draft = adapter.draft_critique(run, trial_stats, self._config)
        claims: List[MetricClaim] = list(draft.get("claims", []))
        findings: List[CriticFinding] = list(draft.get("findings", []))

        # Independently verify every numerical claim against the immutable registry.
        self.verify_claims(claims)

        created_at = utc_now_iso()
        body = {
            "run_id": run.run_id,
            "hypothesis_id": run.hypothesis_id,
            "verdict": draft["verdict"],
            "summary": draft["summary"],
            "findings": [f.to_dict() for f in findings],
            "claims": [c.to_dict() for c in claims],
            "trial_accounting": trial_stats.to_dict(),
            "verified": True,
            "critic_adapter": adapter.adapter_name,
            "created_at_utc": created_at,
        }
        report_hash = sha256_json(body)
        report_id = f"crit_{report_hash[:12]}"
        report = CriticReport(
            report_id=report_id,
            run_id=run.run_id,
            hypothesis_id=run.hypothesis_id,
            verdict=draft["verdict"],
            summary=draft["summary"],
            findings=findings,
            claims=claims,
            trial_accounting=trial_stats.to_dict(),
            verified=True,
            critic_adapter=adapter.adapter_name,
            created_at_utc=created_at,
            report_sha256=report_hash,
        )
        self._registry.store_critic_report(report.to_dict())
        return report
