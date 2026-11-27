"""Integration tests for end-to-end discovery pipeline, trial ledger, and CLI."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from asde.cli import main as cli_main
from asde.dsl.schema import StrategySpec
from asde.export.packager import verify_package
from asde.pipeline import DiscoveryPipeline
from asde.reporting.trial_store import SqliteTrialStore

ROOT = Path(__file__).resolve().parents[2]


class TestPipelineAndCli(unittest.TestCase):
    def test_end_to_end_pipeline_accounts_for_all_trials_including_failures(self) -> None:
        pipeline = DiscoveryPipeline(project_root=ROOT)
        config = json.loads((ROOT / "config" / "default_discovery.json").read_text(encoding="utf-8"))
        config["search"]["max_candidates"] = 6
        config["search"]["max_inner_trials_per_candidate"] = 2
        config["evaluation"]["bootstrap_samples"] = 40

        failing_spec = StrategySpec(
            strategy_id="injected_invalid_code_spec",
            family="trend_ma_crossover",
            dsl_version="1.0.0",
            parameters={
                "fast_window": 10,
                "slow_window": 40,
                "vol_window": 20,
                "target_vol": 0.12,
                "rebalance_band": 0.05,
                "signal_lag_bars": 1,
            },
            raw_code="eval('future')",
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "run_out"
            res = pipeline.run(
                config=config,
                out_dir=out_dir,
                extra_candidate_specs=[failing_spec],
            )

            # Verify baselines and candidates used identical dataset & cost hashes
            lb = res.leaderboard
            ds_fp = lb["dataset_fingerprint"]
            cost_fp = lb["cost_scenario_hash"]
            for b in lb["baselines"]:
                self.assertEqual(b["dataset_fingerprint"], ds_fp)
                self.assertEqual(b["cost_scenario_hash"], cost_fp)
            for c in lb["candidates"]:
                self.assertEqual(c["dataset_fingerprint"], ds_fp)
                self.assertEqual(c["cost_scenario_hash"], cost_fp)

            # Verify failed candidate is recorded in ledger AND leaderboard
            self.assertEqual(len(lb["failed_candidates"]), 1)
            self.assertEqual(lb["failed_candidates"][0]["strategy_id"], "injected_invalid_code_spec")
            store = SqliteTrialStore(out_dir / "trial_ledger.sqlite")
            acc = store.accounting_summary(run_id=res.run_id)
            self.assertGreaterEqual(acc["failed_trials"], 1)
            self.assertEqual(acc["total_trials_recorded"], len(store.list_trials(run_id=res.run_id)))

            # Holdout untouched during selection
            self.assertEqual(lb["holdout_audit"]["holdout_reads_during_selection"], 0)
            self.assertTrue(lb["holdout_audit"]["selection_locked"])

            # Verify exported packages (if any)
            for pkg in res.exported_packages:
                manifest = verify_package(pkg)
                self.assertEqual(manifest["dataset_fingerprint"], ds_fp)
                self.assertEqual(manifest["cost_scenario_hash"], cost_fp)
                self.assertFalse(manifest["order_execution_enabled"])

    def test_cli_discover_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cli_run"
            rc = cli_main(
                [
                    "discover",
                    "--config",
                    str(ROOT / "config" / "default_discovery.json"),
                    "--out",
                    str(out_dir),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "leaderboard.json").exists())
            self.assertTrue((out_dir / "leaderboard.md").exists())
            self.assertTrue((out_dir / "trials.jsonl").exists())
            self.assertTrue((out_dir / "split_manifest.json").exists())

            pkgs_dir = out_dir / "packages"
            self.assertTrue(pkgs_dir.exists(), "Expected at least one review-eligible package exported.")
            pkg_dirs = [p for p in sorted(pkgs_dir.iterdir()) if p.is_dir()]
            self.assertGreaterEqual(len(pkg_dirs), 1)
            for pkg in pkg_dirs[:1]:
                self.assertEqual(cli_main(["verify-package", "--package", str(pkg)]), 0)
                self.assertEqual(
                    cli_main(
                        [
                            "review",
                            "--package",
                            str(pkg),
                            "--reviewer",
                            "independent_reviewer_1",
                            "--decision",
                            "APPROVE_PAPER_ONLY",
                            "--rationale",
                            "Reviewed walk-forward metrics, DSR, and cost sensitivity.",
                        ]
                    ),
                    0,
                )


if __name__ == "__main__":
    unittest.main()
