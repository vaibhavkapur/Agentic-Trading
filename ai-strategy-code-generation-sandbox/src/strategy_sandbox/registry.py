"""Append-only trial registry, artifact hash verification, and human review governance.

Guarantees that no strategy code can be promoted to paper-staging without:
1. A persisted, hash-verified TrialRecord with status == "PASSED" and all checks passing.
2. A persisted HumanReviewRecord with decision == "APPROVE" bound to the exact
   trial_id, code_sha256, and output_sha256.
"""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import (
    CheckResult,
    DatasetManifest,
    ExperimentBudget,
    HumanReviewRecord,
    PromotionDecision,
    StrategyProposal,
    StrategySpec,
    TrialRecord,
)
from .errors import PromotionDeniedError, SandboxError
from .hashing import canonical_json
from .verifier import ExperimentEvaluator, compute_trial_output_hash


class TrialRegistry:
    """File-backed append-only ledger tracking trials, reviews, and promotion gates."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.trials_dir = self.root_dir / "trials"
        self.trials_ledger = self.root_dir / "trials.jsonl"
        self.reviews_ledger = self.root_dir / "reviews.jsonl"
        self.promotions_ledger = self.root_dir / "promotions.jsonl"
        self.trials_dir.mkdir(parents=True, exist_ok=True)

    def record_trial(self, trial: TrialRecord) -> Path:
        """Persist full TrialRecord JSON artifact and append summary entry to trials.jsonl."""
        artifact_path = self.trials_dir / f"{trial.trial_id}.json"
        artifact_path.write_text(
            json.dumps(trial.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ledger_entry = {
            "trial_id": trial.trial_id,
            "created_at": trial.created_at.isoformat().replace("+00:00", "Z"),
            "proposal_id": trial.proposal_id,
            "spec_id": trial.spec_id,
            "dataset_id": trial.dataset_id,
            "status": trial.status,
            "code_sha256": trial.code_sha256,
            "dataset_sha256": trial.dataset_sha256,
            "input_bundle_sha256": trial.input_bundle_sha256,
            "output_sha256": trial.output_sha256,
        }
        with self.trials_ledger.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(ledger_entry) + "\n")
        return artifact_path

    def get_trial(self, trial_id: str) -> TrialRecord:
        artifact_path = self.trials_dir / f"{trial_id}.json"
        if not artifact_path.exists():
            raise SandboxError(f"Trial '{trial_id}' not found in registry.", details={"trial_id": trial_id})
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
        return TrialRecord.model_validate(raw)

    def list_trials(self) -> list[dict[str, str]]:
        if not self.trials_ledger.exists():
            return []
        entries: list[dict[str, str]] = []
        for line in self.trials_ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def verify_trial_integrity(self, trial_id: str) -> CheckResult:
        """Verify stored trial artifact has not been tampered with since recording."""
        trial = self.get_trial(trial_id)
        recomputed = compute_trial_output_hash(
            status=trial.status,
            checks=trial.checks,
            accounting=trial.accounting,
            fills=trial.fills,
            rejected_orders=trial.rejected_orders,
            equity_curve=trial.equity_curve,
        )
        if recomputed != trial.output_sha256:
            return CheckResult(
                name="artifact_integrity",
                passed=False,
                code="ARTIFACT_HASH_MISMATCH",
                message=f"Stored trial '{trial_id}' failed integrity check (expected {trial.output_sha256}, computed {recomputed}).",
                details={"expected": trial.output_sha256, "computed": recomputed},
            )
        return CheckResult(
            name="artifact_integrity",
            passed=True,
            code="OK",
            message=f"Trial '{trial_id}' artifact hash verified ({recomputed[:12]}).",
            details={"output_sha256": recomputed},
        )

    def record_human_review(
        self,
        *,
        review_id: str,
        trial_id: str,
        reviewer: str,
        decision: str,
        notes: str = "",
        code_sha256: str | None = None,
        output_sha256: str | None = None,
    ) -> HumanReviewRecord:
        """Record a human review bound to immutable trial artifact hashes."""
        trial = self.get_trial(trial_id)
        review = HumanReviewRecord(
            review_id=review_id,
            trial_id=trial_id,
            reviewer=reviewer,
            decision=decision,  # type: ignore[arg-type]
            code_sha256=code_sha256 or trial.code_sha256,
            output_sha256=output_sha256 or trial.output_sha256,
            notes=notes,
        )
        with self.reviews_ledger.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(review.model_dump(mode="json")) + "\n")
        return review

    def list_reviews(self, trial_id: str | None = None) -> list[HumanReviewRecord]:
        if not self.reviews_ledger.exists():
            return []
        reviews: list[HumanReviewRecord] = []
        for line in self.reviews_ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = HumanReviewRecord.model_validate(json.loads(line))
            if trial_id is None or rec.trial_id == trial_id:
                reviews.append(rec)
        return reviews

    def promote_trial(self, trial_id: str, *, review_id: str | None = None) -> PromotionDecision:
        """Enforce promotion governance: validation PASS + hash integrity + matching human APPROVE."""
        try:
            trial = self.get_trial(trial_id)
        except SandboxError as exc:
            raise PromotionDeniedError(
                f"Cannot promote unknown trial '{trial_id}'.",
                details={"trial_id": trial_id},
            ) from exc

        integrity = self.verify_trial_integrity(trial_id)
        if not integrity.passed:
            self._deny_promotion(trial, reason=integrity.message)

        if trial.status != "PASSED" or any(not chk.passed for chk in trial.checks):
            failed_names = [c.name for c in trial.checks if not c.passed]
            self._deny_promotion(
                trial,
                reason=f"Trial status is '{trial.status}' (failed checks: {failed_names}); unvalidated code cannot be promoted.",
            )

        reviews = self.list_reviews(trial_id=trial_id)
        if review_id is not None:
            reviews = [r for r in reviews if r.review_id == review_id]

        matching_approvals = [
            r
            for r in reviews
            if r.decision == "APPROVE"
            and r.code_sha256 == trial.code_sha256
            and r.output_sha256 == trial.output_sha256
        ]
        if not matching_approvals:
            self._deny_promotion(
                trial,
                reason=(
                    f"No matching human APPROVE review found for trial '{trial_id}' "
                    f"with code_sha256={trial.code_sha256[:12]} and output_sha256={trial.output_sha256[:12]}."
                ),
            )

        chosen = matching_approvals[-1]
        decision = PromotionDecision(
            trial_id=trial.trial_id,
            promoted=True,
            stage="PAPER_STAGING_APPROVED",
            code_sha256=trial.code_sha256,
            output_sha256=trial.output_sha256,
            review_id=chosen.review_id,
            reviewer=chosen.reviewer,
            reason=f"All validation gates passed and verified human review '{chosen.review_id}' approved.",
        )
        self._append_promotion(decision)
        return decision

    def replay_trial(
        self,
        *,
        trial_id: str,
        proposal: StrategyProposal,
        spec: StrategySpec,
        dataset: DatasetManifest,
        evaluator: ExperimentEvaluator,
        budget: ExperimentBudget | None = None,
        reference_expected: dict | None = None,
    ) -> CheckResult:
        """Re-execute a recorded trial and verify bit-for-bit logical reproducibility."""
        stored = self.get_trial(trial_id)
        replayed = evaluator.evaluate(
            proposal=proposal,
            spec=spec,
            dataset=dataset,
            budget=budget,
            reference_expected=reference_expected,
        )
        matches = (
            replayed.input_bundle_sha256 == stored.input_bundle_sha256
            and replayed.output_sha256 == stored.output_sha256
            and replayed.status == stored.status
        )
        return CheckResult(
            name="trial_replay",
            passed=matches,
            code="OK" if matches else "REPLAY_MISMATCH",
            message=(
                f"Replay of '{trial_id}' reproduced identical output hash {replayed.output_sha256[:12]}."
                if matches
                else f"Replay mismatch for '{trial_id}': stored={stored.output_sha256[:12]}, replayed={replayed.output_sha256[:12]}."
            ),
            details={
                "stored_trial_id": stored.trial_id,
                "replayed_trial_id": replayed.trial_id,
                "stored_output_sha256": stored.output_sha256,
                "replayed_output_sha256": replayed.output_sha256,
            },
        )

    def _append_promotion(self, decision: PromotionDecision) -> None:
        with self.promotions_ledger.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(decision.model_dump(mode="json")) + "\n")

    def _deny_promotion(self, trial: TrialRecord, *, reason: str) -> None:
        decision = PromotionDecision(
            trial_id=trial.trial_id,
            promoted=False,
            stage="REJECTED",
            code_sha256=trial.code_sha256,
            output_sha256=trial.output_sha256,
            reason=reason,
        )
        self._append_promotion(decision)
        raise PromotionDeniedError(reason, details=decision.model_dump(mode="json"))
