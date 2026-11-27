"""Unit tests for Immutable RunRegistry, Separation of Duties, Live-Mode Ban, and TS-14 Adapter."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rarp.critic.critic import ResearchCritic
from rarp.domain.dsl import CostModelSpec, ExperimentSpec, HypothesisSpec, SplitSpec
from rarp.domain.errors import PolicyViolationError, ReviewGateError
from rarp.domain.types import RunStatus
from rarp.governance.review import PromotionGate
from rarp.governance.signing import ArtifactSigner
from rarp.registry.memory import compute_trial_adjusted_stats
from rarp.registry.store import RunRegistry
from rarp.scheduler.backtester import TS14BacktesterAdapter


class TestRegistryImmutabilityAndGovernance(unittest.TestCase):
    def _sample_spec(self, proposer_id: str = "agent_proposer") -> ExperimentSpec:
        hyp = HypothesisSpec(
            hypothesis_id="hyp_gov_1",
            title="Gov test",
            rationale="Testing review gate",
            family="momentum_crossover",
            parameters={
                "fast_window": 5,
                "slow_window": 25,
                "signal_lag_bars": 1,
                "vol_target_annual": 0.15,
            },
            universe=("SYN_EQ_A",),
            proposer_id=proposer_id,
            created_at_utc="2026-01-01T00:00:00Z",
        )
        return ExperimentSpec(
            experiment_id="exp_gov_1",
            hypothesis=hyp,
            data_manifest_id="man_1",
            data_manifest_sha256="deadbeef",
            split=SplitSpec(),
            cost_model=CostModelSpec("baseline"),
            seed=42,
        )

    def test_registry_triggers_block_update_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = RunRegistry(Path(tmp))
            spec = self._sample_spec()
            uri, digest = reg.put_artifact("runs/exp_gov_1.json", {"ok": True})
            rec = reg.record_run(
                spec=spec,
                status=RunStatus.SUCCEEDED,
                metrics={"validation_sharpe": 0.85, "train_sharpe": 0.90, "validation_max_drawdown": 0.10, "validation_trade_count": 12.0, "validation_cost_drag_return": 0.01, "train_val_sharpe_gap": 0.05},
                artifact_uri=uri,
                artifact_sha256=digest,
                split_sha256="split_hash",
                attempts=1,
                started_at_utc="2026-01-01T00:00:00Z",
                completed_at_utc="2026-01-01T00:01:00Z",
                error_code=None,
                error_message=None,
            )
            self.assertTrue(reg.verify_hash_chain())

            conn = sqlite3.connect(str(reg.db_path))
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE runs SET status = 'FAILED' WHERE run_id = ?", (rec.run_id,))
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM runs WHERE run_id = ?", (rec.run_id,))
            conn.close()

    def test_promotion_gate_enforces_independent_reviewer_and_paper_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = RunRegistry(Path(tmp))
            signer = ArtifactSigner(secret_key="gov-test-key")
            gate = PromotionGate(reg, signer)
            spec = self._sample_spec(proposer_id="researcher_bob")
            uri, digest = reg.put_artifact("runs/exp_gov_1.json", {"ok": True})
            rec = reg.record_run(
                spec=spec,
                status=RunStatus.SUCCEEDED,
                metrics={
                    "train_sharpe": 0.95,
                    "validation_sharpe": 0.80,
                    "validation_max_drawdown": 0.10,
                    "validation_trade_count": 15.0,
                    "validation_cost_drag_return": 0.005,
                    "train_val_sharpe_gap": 0.15,
                },
                artifact_uri=uri,
                artifact_sha256=digest,
                split_sha256="split_hash",
                attempts=1,
                started_at_utc="2026-01-01T00:00:00Z",
                completed_at_utc="2026-01-01T00:01:00Z",
                error_code=None,
                error_message=None,
            )

            # Without critic report, promotion must fail.
            with self.assertRaises(ReviewGateError):
                gate.submit_decision(rec.run_id, reviewer_id="reviewer_alice", approve=True)

            # Attach verified critic report.
            critic = ResearchCritic(reg)
            critic.evaluate_run(rec, compute_trial_adjusted_stats(0.80, 100, 1))

            # Self-approval by proposer must fail.
            with self.assertRaises(ReviewGateError):
                gate.submit_decision(rec.run_id, reviewer_id="researcher_bob", approve=True)

            # Automated agent self-review must fail.
            with self.assertRaises(ReviewGateError):
                gate.submit_decision(rec.run_id, reviewer_id="agent_reviewer", approve=True)

            # Live deployment target is strictly prohibited.
            with self.assertRaises(PolicyViolationError):
                gate.submit_decision(
                    rec.run_id,
                    reviewer_id="reviewer_alice",
                    approve=True,
                    target_environment="LIVE",
                )

            # Independent human reviewer approving PAPER_SANDBOX succeeds with execution disabled.
            decision, pkg = gate.submit_decision(
                rec.run_id,
                reviewer_id="reviewer_alice",
                approve=True,
                target_environment="PAPER_SANDBOX",
                notes="Paper sandbox verified",
            )
            self.assertEqual(decision.decision, "APPROVED_PAPER_ONLY")
            self.assertIsNotNone(pkg)
            assert pkg is not None
            self.assertFalse(pkg.order_execution_enabled)
            self.assertTrue(pkg.live_deployment_prohibited)
            self.assertTrue(signer.verify(pkg.signed_artifact))

    def test_ts14_adapter_blocks_unvetted_external_copy(self) -> None:
        with self.assertRaises(PolicyViolationError):
            TS14BacktesterAdapter(allow_external=True)


if __name__ == "__main__":
    unittest.main()
