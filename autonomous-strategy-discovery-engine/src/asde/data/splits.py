"""Immutable chronological split manifests, walk-forward folds, and holdout leakage guard."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Tuple

from asde.errors import DataContractError, HoldoutLeakageError, ManifestIntegrityError
from asde.types import DatasetSnapshot, sha256_canonical


@dataclass(frozen=True)
class SplitPolicy:
    train_ratio: float = 0.55
    validation_ratio: float = 0.25
    test_ratio: float = 0.20
    embargo_bars: int = 5
    walk_forward_folds: int = 4
    inner_tuning_folds: int = 3
    min_train_bars: int = 120
    min_fold_bars: int = 40

    def validate(self) -> None:
        total = self.train_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-6:
            raise DataContractError(f"Split ratios must sum to 1.0, got {total}")
        if self.train_ratio <= 0 or self.validation_ratio <= 0 or self.test_ratio <= 0:
            raise DataContractError("All split ratios must be strictly positive.")
        if self.embargo_bars < 0:
            raise DataContractError("embargo_bars must be >= 0.")
        if self.walk_forward_folds < 2:
            raise DataContractError("walk_forward_folds must be >= 2.")
        if self.inner_tuning_folds < 2:
            raise DataContractError("inner_tuning_folds must be >= 2.")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FoldSpec:
    """Chronological, embargoed train/validation fold."""

    fold_id: str
    train_start: int
    train_end: int  # exclusive
    val_start: int
    val_end: int  # exclusive
    embargo_bars: int
    train_start_utc: str
    train_end_utc: str
    val_start_utc: str
    val_end_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SplitManifest:
    """Immutable split manifest with cryptographic hash preventing silent drift or tampering."""

    schema_version: str
    dataset_fingerprint: str
    total_bars: int
    embargo_bars: int
    train_start: int
    train_end: int
    val_start: int
    val_end: int
    test_start: int
    test_end: int
    train_start_utc: str
    train_end_utc: str
    val_start_utc: str
    val_end_utc: str
    test_start_utc: str
    test_end_utc: str
    walk_forward_folds: List[FoldSpec]
    inner_folds: List[FoldSpec]
    manifest_hash: str

    def payload_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_fingerprint": self.dataset_fingerprint,
            "total_bars": self.total_bars,
            "embargo_bars": self.embargo_bars,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "val_start": self.val_start,
            "val_end": self.val_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "train_start_utc": self.train_start_utc,
            "train_end_utc": self.train_end_utc,
            "val_start_utc": self.val_start_utc,
            "val_end_utc": self.val_end_utc,
            "test_start_utc": self.test_start_utc,
            "test_end_utc": self.test_end_utc,
            "walk_forward_folds": [f.to_dict() for f in self.walk_forward_folds],
            "inner_folds": [f.to_dict() for f in self.inner_folds],
        }

    def to_dict(self) -> Dict[str, Any]:
        d = self.payload_dict()
        d["manifest_hash"] = self.manifest_hash
        return d


def build_split_manifest(dataset: DatasetSnapshot, policy: SplitPolicy) -> SplitManifest:
    """Construct an immutable chronological split manifest with purge/embargo gaps."""
    policy.validate()
    n = dataset.num_bars
    ts = dataset.timestamps_utc
    embargo = policy.embargo_bars

    raw_train_end = int(n * policy.train_ratio)
    raw_val_end = int(n * (policy.train_ratio + policy.validation_ratio))

    train_start = 0
    train_end = raw_train_end - embargo
    val_start = raw_train_end
    val_end = raw_val_end - embargo
    test_start = raw_val_end
    test_end = n

    if train_end - train_start < policy.min_train_bars:
        raise DataContractError(
            f"Insufficient train bars ({train_end - train_start}) for min_train_bars={policy.min_train_bars}."
        )
    if val_end - val_start < policy.min_fold_bars:
        raise DataContractError("Insufficient validation bars for split policy.")
    if test_end - test_start < policy.min_fold_bars:
        raise DataContractError("Insufficient holdout test bars for split policy.")

    # Non-overlapping expanding walk-forward validation folds spanning [val_start, val_end)
    # Every fold's validation window is strictly < test_start and strictly non-overlapping.
    wf_folds = _build_expanding_folds(
        prefix="wf",
        timestamps=ts,
        region_start=0,
        eval_start=val_start,
        eval_end=val_end,
        num_folds=policy.walk_forward_folds,
        embargo=embargo,
        min_fold_bars=policy.min_fold_bars,
    )

    # Inner tuning folds strictly inside [train_start, train_end) for nested parameter tuning
    inner_eval_start = max(policy.min_train_bars, train_start + int((train_end - train_start) * 0.45))
    inner_folds = _build_expanding_folds(
        prefix="inner",
        timestamps=ts,
        region_start=train_start,
        eval_start=inner_eval_start,
        eval_end=train_end,
        num_folds=policy.inner_tuning_folds,
        embargo=embargo,
        min_fold_bars=max(20, policy.min_fold_bars // 2),
    )

    payload = {
        "schema_version": "1.0.0",
        "dataset_fingerprint": dataset.fingerprint,
        "total_bars": n,
        "embargo_bars": embargo,
        "train_start": train_start,
        "train_end": train_end,
        "val_start": val_start,
        "val_end": val_end,
        "test_start": test_start,
        "test_end": test_end,
        "train_start_utc": ts[train_start],
        "train_end_utc": ts[train_end - 1],
        "val_start_utc": ts[val_start],
        "val_end_utc": ts[val_end - 1],
        "test_start_utc": ts[test_start],
        "test_end_utc": ts[test_end - 1],
        "walk_forward_folds": [f.to_dict() for f in wf_folds],
        "inner_folds": [f.to_dict() for f in inner_folds],
    }
    manifest_hash = sha256_canonical(payload)
    manifest = SplitManifest(
        schema_version="1.0.0",
        dataset_fingerprint=dataset.fingerprint,
        total_bars=n,
        embargo_bars=embargo,
        train_start=train_start,
        train_end=train_end,
        val_start=val_start,
        val_end=val_end,
        test_start=test_start,
        test_end=test_end,
        train_start_utc=ts[train_start],
        train_end_utc=ts[train_end - 1],
        val_start_utc=ts[val_start],
        val_end_utc=ts[val_end - 1],
        test_start_utc=ts[test_start],
        test_end_utc=ts[test_end - 1],
        walk_forward_folds=wf_folds,
        inner_folds=inner_folds,
        manifest_hash=manifest_hash,
    )
    verify_split_manifest(manifest, dataset)
    return manifest


def _build_expanding_folds(
    *,
    prefix: str,
    timestamps: List[str],
    region_start: int,
    eval_start: int,
    eval_end: int,
    num_folds: int,
    embargo: int,
    min_fold_bars: int,
) -> List[FoldSpec]:
    span = eval_end - eval_start
    fold_len = span // num_folds
    if fold_len < min_fold_bars:
        raise DataContractError(
            f"Cannot build {num_folds} folds of >= {min_fold_bars} bars inside span {span}."
        )
    folds: List[FoldSpec] = []
    for k in range(num_folds):
        v_start = eval_start + k * fold_len
        v_end = eval_end if k == num_folds - 1 else v_start + fold_len
        t_end = v_start - embargo
        if t_end <= region_start:
            raise DataContractError(f"Fold {prefix}_{k} has non-positive train span.")
        folds.append(
            FoldSpec(
                fold_id=f"{prefix}_fold_{k + 1}",
                train_start=region_start,
                train_end=t_end,
                val_start=v_start,
                val_end=v_end,
                embargo_bars=embargo,
                train_start_utc=timestamps[region_start],
                train_end_utc=timestamps[t_end - 1],
                val_start_utc=timestamps[v_start],
                val_end_utc=timestamps[v_end - 1],
            )
        )
    return folds


def verify_split_manifest(manifest: SplitManifest, dataset: DatasetSnapshot) -> None:
    """Verify cryptographic integrity and strict non-overlapping chronological boundaries."""
    expected_hash = sha256_canonical(manifest.payload_dict())
    if expected_hash != manifest.manifest_hash:
        raise ManifestIntegrityError(
            "Split manifest hash verification failed; manifest was tampered with.",
            details={"expected": expected_hash, "actual": manifest.manifest_hash},
        )
    if manifest.dataset_fingerprint != dataset.fingerprint:
        raise ManifestIntegrityError(
            "Split manifest dataset_fingerprint does not match loaded dataset.",
            details={
                "manifest_dataset": manifest.dataset_fingerprint,
                "actual_dataset": dataset.fingerprint,
            },
        )
    if not (
        0 <= manifest.train_start < manifest.train_end
        and manifest.train_end + manifest.embargo_bars <= manifest.val_start < manifest.val_end
        and manifest.val_end + manifest.embargo_bars <= manifest.test_start < manifest.test_end <= dataset.num_bars
    ):
        raise ManifestIntegrityError("Split manifest chronological boundaries or embargo gaps violated.")

    # Verify walk-forward folds never overlap each other and never enter holdout test split
    prev_val_end = -1
    for fold in manifest.walk_forward_folds:
        if fold.val_start < prev_val_end:
            raise ManifestIntegrityError(f"Overlapping walk-forward fold detected: {fold.fold_id}")
        if fold.train_end + fold.embargo_bars > fold.val_start:
            raise ManifestIntegrityError(f"Embargo violation inside fold {fold.fold_id}")
        if fold.val_end > manifest.val_end or fold.val_end > manifest.test_start:
            raise HoldoutLeakageError(
                f"Walk-forward fold {fold.fold_id} leaks into holdout test split.",
                details={"fold_val_end": fold.val_end, "test_start": manifest.test_start},
            )
        prev_val_end = fold.val_end

    # Verify inner folds stay strictly inside train split
    prev_inner_end = -1
    for fold in manifest.inner_folds:
        if fold.val_start < prev_inner_end:
            raise ManifestIntegrityError(f"Overlapping inner fold detected: {fold.fold_id}")
        if fold.val_end > manifest.train_end:
            raise HoldoutLeakageError(
                f"Inner fold {fold.fold_id} leaks outside train split into validation/test.",
                details={"fold_val_end": fold.val_end, "train_end": manifest.train_end},
            )
        prev_inner_end = fold.val_end


@dataclass
class HoldoutAccessEvent:
    phase: str
    requester: str
    split_name: str
    start_idx: int
    end_idx: int
    allowed: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HoldoutGuard:
    """Enforces that the holdout test split is untouched during candidate selection."""

    def __init__(self, manifest: SplitManifest) -> None:
        self.manifest = manifest
        self._selection_locked: bool = False
        self._audit_log: List[HoldoutAccessEvent] = []
        self._holdout_reads_during_selection: int = 0
        self._holdout_reads_after_lock: int = 0

    @property
    def selection_locked(self) -> bool:
        return self._selection_locked

    @property
    def audit_log(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._audit_log]

    @property
    def holdout_reads_during_selection(self) -> int:
        return self._holdout_reads_during_selection

    def request_slice(
        self,
        *,
        split_name: str,
        start_idx: int,
        end_idx: int,
        phase: str,
        requester: str,
    ) -> Tuple[int, int]:
        """Authorize a bar index slice, blocking any leakage into the holdout test split."""
        touches_holdout = split_name == "test" or end_idx > self.manifest.test_start or start_idx >= self.manifest.test_start
        if touches_holdout:
            if not self._selection_locked or phase != "locked_holdout_evaluation":
                event = HoldoutAccessEvent(
                    phase=phase,
                    requester=requester,
                    split_name=split_name,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    allowed=False,
                    reason="Holdout test split is forbidden before candidate selection is locked.",
                )
                self._audit_log.append(event)
                raise HoldoutLeakageError(
                    f"Holdout leakage blocked: requester={requester!r} attempted to read "
                    f"[{start_idx}, {end_idx}) (test_start={self.manifest.test_start}) during phase={phase!r}.",
                    details=event.to_dict(),
                )
            self._holdout_reads_after_lock += 1
        elif split_name == "inner" and end_idx > self.manifest.train_end:
            event = HoldoutAccessEvent(
                phase=phase,
                requester=requester,
                split_name=split_name,
                start_idx=start_idx,
                end_idx=end_idx,
                allowed=False,
                reason="Inner tuning slice cannot extend beyond train_end.",
            )
            self._audit_log.append(event)
            raise HoldoutLeakageError(
                f"Validation leakage blocked during inner tuning: [{start_idx}, {end_idx}) > train_end={self.manifest.train_end}.",
                details=event.to_dict(),
            )

        self._audit_log.append(
            HoldoutAccessEvent(
                phase=phase,
                requester=requester,
                split_name=split_name,
                start_idx=start_idx,
                end_idx=end_idx,
                allowed=True,
                reason="authorized",
            )
        )
        return start_idx, end_idx

    def lock_selection(self) -> None:
        """Freeze candidate selection prior to optional one-time final holdout verification."""
        self._selection_locked = True

    def summary(self) -> Dict[str, Any]:
        blocked = [e for e in self._audit_log if not e.allowed]
        return {
            "manifest_hash": self.manifest.manifest_hash,
            "selection_locked": self._selection_locked,
            "holdout_reads_during_selection": self._holdout_reads_during_selection,
            "holdout_reads_after_lock": self._holdout_reads_after_lock,
            "blocked_attempts": len(blocked),
            "total_authorized_reads": len(self._audit_log) - len(blocked),
        }
