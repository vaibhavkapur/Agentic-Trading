"""Unit tests for strategy package export, verification, and independent review gate."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from asde.dsl.schema import StrategySpec
from asde.errors import GovernanceViolationError, ManifestIntegrityError
from asde.export.packager import StrategyPackager, verify_package
from asde.export.review import ReviewDecision


class TestPackagerAndReview(unittest.TestCase):
    def _export_sample(self, out_dir: Path, *, status: str = "ELIGIBLE_FOR_REVIEW", cost: str = "base_institutional") -> Path:
        packager = StrategyPackager()
        spec = StrategySpec(
            strategy_id="trend_sample_01",
            family="trend_ma_crossover",
            dsl_version="1.0.0",
            parameters={
                "fast_window": 10,
                "slow_window": 50,
                "vol_window": 20,
                "target_vol": 0.12,
                "rebalance_band": 0.05,
                "signal_lag_bars": 1,
            },
        )
        return packager.export_candidate(
            out_dir=out_dir,
            run_id="run_test_01",
            spec=spec,
            config_snapshot={"seed": 42},
            dataset_manifest={"dataset_id": "syn_1", "data_sha256": "abc123"},
            dataset_fingerprint="dfp_123",
            split_manifest={"manifest_hash": "smh_123"},
            catalog_fingerprint="cfp_123",
            primary_cost_scenario=cost,
            cost_scenario_hash="csh_123",
            evaluation_evidence={
                "governance_status": status,
                "rejection_reasons": [] if status == "ELIGIBLE_FOR_REVIEW" else ["failed_deflated_sharpe"],
                "holdout_audit": {"holdout_reads_during_selection": 0},
            },
            seed=42,
        )

    def test_package_verification_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self._export_sample(Path(tmp))
            manifest = verify_package(pkg)
            self.assertFalse(manifest["order_execution_enabled"])
            self.assertFalse(manifest["live_execution_permitted"])

            # Tamper with strategy_spec.json
            sp = pkg / "strategy_spec.json"
            data = json.loads(sp.read_text(encoding="utf-8"))
            data["parameters"]["fast_window"] = 99
            sp.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestIntegrityError):
                verify_package(pkg)

    def test_review_gate_enforces_governance_and_blocks_live_execution(self) -> None:
        packager = StrategyPackager()
        full_checklist = {
            "verified_no_holdout_leakage": True,
            "verified_realistic_costs": True,
            "verified_multiple_testing_stats": True,
            "verified_turnover_and_drawdown": True,
            "verified_data_entitlements": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self._export_sample(Path(tmp))

            # Self-review blocked
            with self.assertRaises(GovernanceViolationError):
                packager.apply_independent_review(
                    package_dir=pkg,
                    decision=ReviewDecision(
                        reviewer_id="asde_engine",
                        reviewer_role="bot",
                        decision="APPROVE_PAPER_ONLY",
                        rationale="self approve",
                        reviewed_at_utc="2026-04-01T12:00:00Z",
                        checklist_verified=full_checklist,
                    ),
                )

            # Live target blocked
            with self.assertRaises(GovernanceViolationError):
                packager.apply_independent_review(
                    package_dir=pkg,
                    decision=ReviewDecision(
                        reviewer_id="alice_risk",
                        reviewer_role="risk_officer",
                        decision="APPROVE_PAPER_ONLY",
                        rationale="ship to live",
                        reviewed_at_utc="2026-04-01T12:00:00Z",
                        checklist_verified=full_checklist,
                        requested_target="live_production",
                    ),
                )

            # Valid independent approval permits paper_sandbox only, keeps live disabled
            rec = packager.apply_independent_review(
                package_dir=pkg,
                decision=ReviewDecision(
                    reviewer_id="alice_risk",
                    reviewer_role="independent_risk_reviewer",
                    decision="APPROVE_PAPER_ONLY",
                    rationale="Verified walk-forward stability, DSR, and realistic cost stress.",
                    reviewed_at_utc="2026-04-01T12:00:00Z",
                    checklist_verified=full_checklist,
                    requested_target="paper_sandbox",
                ),
            )
            self.assertEqual(rec["review_status"], "APPROVED_FOR_PAPER_SANDBOX")
            self.assertTrue(rec["paper_execution_permitted"])
            self.assertFalse(rec["live_execution_permitted"])
            self.assertFalse(rec["order_execution_enabled"])

            # Zero-cost package cannot be approved
            pkg_zero = self._export_sample(Path(tmp) / "zero", cost="zero_cost_reference")
            with self.assertRaises(GovernanceViolationError):
                packager.apply_independent_review(
                    package_dir=pkg_zero,
                    decision=ReviewDecision(
                        reviewer_id="alice_risk",
                        reviewer_role="risk_officer",
                        decision="APPROVE_PAPER_ONLY",
                        rationale="approve zero cost",
                        reviewed_at_utc="2026-04-01T12:00:00Z",
                        checklist_verified=full_checklist,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
