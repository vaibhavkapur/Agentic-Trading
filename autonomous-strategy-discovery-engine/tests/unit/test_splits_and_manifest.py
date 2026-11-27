"""Unit tests for dataset manifest integrity, immutable split manifests, and HoldoutGuard."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from asde.data.fixtures import (
    generate_synthetic_dataset,
    load_dataset_from_manifest,
    write_dataset_fixture,
)
from asde.data.splits import (
    HoldoutGuard,
    SplitPolicy,
    build_split_manifest,
    verify_split_manifest,
)
from asde.errors import HoldoutLeakageError, ManifestIntegrityError


class TestSplitsAndManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = generate_synthetic_dataset(seed=77, num_bars=700)
        self.policy = SplitPolicy(
            train_ratio=0.55,
            validation_ratio=0.25,
            test_ratio=0.20,
            embargo_bars=5,
            walk_forward_folds=3,
            inner_tuning_folds=3,
            min_train_bars=100,
            min_fold_bars=30,
        )
        self.manifest = build_split_manifest(self.dataset, self.policy)

    def test_chronological_non_overlapping_embargo_invariants(self) -> None:
        m = self.manifest
        self.assertLess(m.train_end, m.val_start)
        self.assertGreaterEqual(m.val_start - m.train_end, m.embargo_bars)
        self.assertLess(m.val_end, m.test_start)
        self.assertGreaterEqual(m.test_start - m.val_end, m.embargo_bars)

        prev_end = -1
        for f in m.walk_forward_folds:
            self.assertGreaterEqual(f.val_start, prev_end)
            self.assertLessEqual(f.val_end, m.val_end)
            self.assertLess(f.val_end, m.test_start)
            prev_end = f.val_end

        for f in m.inner_folds:
            self.assertLessEqual(f.val_end, m.train_end)

    def test_tampered_split_manifest_rejected(self) -> None:
        tampered = replace(self.manifest, test_start=self.manifest.test_start - 10)
        with self.assertRaises(ManifestIntegrityError):
            verify_split_manifest(tampered, self.dataset)

    def test_tampered_fixture_csv_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mpath = write_dataset_fixture(self.dataset, tmp_path)
            loaded = load_dataset_from_manifest(mpath)
            self.assertEqual(loaded.num_bars, self.dataset.num_bars)

            # Corrupt CSV byte
            csv_path = tmp_path / "synthetic_equities_daily.csv"
            csv_path.write_text(csv_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ManifestIntegrityError):
                load_dataset_from_manifest(mpath)

    def test_holdout_guard_blocks_pre_lock_and_allows_post_lock(self) -> None:
        guard = HoldoutGuard(self.manifest)
        # Valid validation slice succeeds
        guard.request_slice(
            split_name="validation",
            start_idx=self.manifest.val_start,
            end_idx=self.manifest.val_end,
            phase="walk_forward_validation",
            requester="test",
        )
        # Reading test split before lock raises HoldoutLeakageError
        with self.assertRaises(HoldoutLeakageError):
            guard.request_slice(
                split_name="test",
                start_idx=self.manifest.test_start,
                end_idx=self.manifest.test_end,
                phase="walk_forward_validation",
                requester="cheating_selector",
            )
        # Reading inner slice extending into validation raises HoldoutLeakageError
        with self.assertRaises(HoldoutLeakageError):
            guard.request_slice(
                split_name="inner",
                start_idx=self.manifest.train_start,
                end_idx=self.manifest.val_start + 5,
                phase="inner_tuning",
                requester="cheating_tuner",
            )
        self.assertEqual(guard.holdout_reads_during_selection, 0)
        self.assertEqual(guard.summary()["blocked_attempts"], 2)

        guard.lock_selection()
        guard.request_slice(
            split_name="test",
            start_idx=self.manifest.test_start,
            end_idx=self.manifest.test_end,
            phase="locked_holdout_evaluation",
            requester="final_audit",
        )
        self.assertEqual(guard.summary()["holdout_reads_after_lock"], 1)


if __name__ == "__main__":
    unittest.main()
