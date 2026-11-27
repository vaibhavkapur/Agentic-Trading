"""Unit tests for Hypothesis/Experiment DSL, DAG, BudgetTracker, Trial Accounting, and Signing."""

from __future__ import annotations

import unittest
from pathlib import Path

from rarp.domain.dsl import (
    BudgetSpec,
    CostModelSpec,
    ExperimentSpec,
    HypothesisSpec,
    SplitSpec,
    StopConditionsSpec,
    load_strategy_catalog,
)
from rarp.domain.errors import (
    ArtifactSignatureError,
    BudgetExhaustedError,
    PolicyViolationError,
    RARPValidationError,
)
from rarp.governance.signing import ArtifactSigner, SignedResearchArtifact
from rarp.registry.memory import compute_trial_adjusted_stats
from rarp.scheduler.budget import BudgetTracker
from rarp.scheduler.dag import DAGNode, NodeType, ResearchDAG

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "config" / "strategy_catalog.json"


class TestDSLAndCatalog(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_strategy_catalog(CATALOG_PATH)

    def _valid_hypothesis(self, **overrides) -> HypothesisSpec:
        base = dict(
            hypothesis_id="hyp_unit_1",
            title="Valid momentum hypothesis",
            rationale="Causal dual MA test",
            family="momentum_crossover",
            parameters={
                "fast_window": 5,
                "slow_window": 25,
                "signal_lag_bars": 1,
                "vol_target_annual": 0.15,
            },
            universe=("SYN_EQ_A", "SYN_EQ_B"),
            proposer_id="proposer_bot",
            created_at_utc="2026-01-01T00:00:00Z",
        )
        base.update(overrides)
        return HypothesisSpec(**base)

    def test_valid_hypothesis_and_canonical_fingerprint(self) -> None:
        h1 = self._valid_hypothesis(hypothesis_id="h1", universe=("SYN_EQ_B", "SYN_EQ_A"))
        h2 = self._valid_hypothesis(hypothesis_id="h2", universe=("SYN_EQ_A", "SYN_EQ_B"))
        h1.validate(self.catalog)
        h2.validate(self.catalog)
        self.assertEqual(h1.semantic_fingerprint(), h2.semantic_fingerprint())

    def test_unrestricted_code_tokens_are_rejected(self) -> None:
        bad = self._valid_hypothesis(rationale="Use eval('1+1') to build dynamic alpha")
        with self.assertRaises(PolicyViolationError):
            bad.validate(self.catalog)

        bad_param = self._valid_hypothesis(
            parameters={
                "fast_window": 5,
                "slow_window": 25,
                "signal_lag_bars": 1,
                "vol_target_annual": 0.15,
                "code": "return close.shift(-1)",
            }
        )
        with self.assertRaises(PolicyViolationError):
            bad_param.validate(self.catalog)

    def test_parameter_bounds_and_relational_constraints(self) -> None:
        # fast_window >= slow_window violates relational constraint.
        bad_order = self._valid_hypothesis(
            parameters={
                "fast_window": 25,
                "slow_window": 20,
                "signal_lag_bars": 1,
                "vol_target_annual": 0.15,
            }
        )
        with self.assertRaises(RARPValidationError):
            bad_order.validate(self.catalog)

        # Zero lag violates causal invariant.
        bad_lag = self._valid_hypothesis(
            parameters={
                "fast_window": 5,
                "slow_window": 20,
                "signal_lag_bars": 0,
                "vol_target_annual": 0.15,
            }
        )
        with self.assertRaises(RARPValidationError):
            bad_lag.validate(self.catalog)

        # Unknown family rejected.
        bad_fam = self._valid_hypothesis(family="unregistered_neural_net")
        with self.assertRaises(RARPValidationError):
            bad_fam.validate(self.catalog)

    def test_experiment_spec_idempotency_key_stability(self) -> None:
        h = self._valid_hypothesis()
        spec1 = ExperimentSpec(
            experiment_id="exp_1",
            hypothesis=h,
            data_manifest_id="man_1",
            data_manifest_sha256="abc123",
            split=SplitSpec(),
            cost_model=CostModelSpec("baseline"),
            seed=42,
        )
        spec2 = ExperimentSpec(
            experiment_id="exp_2",
            hypothesis=h,
            data_manifest_id="man_1",
            data_manifest_sha256="abc123",
            split=SplitSpec(),
            cost_model=CostModelSpec("baseline"),
            seed=42,
        )
        spec1.validate(self.catalog)
        self.assertEqual(spec1.idempotency_key(), spec2.idempotency_key())


class TestDAGAndBudgetAndSigning(unittest.TestCase):
    def test_dag_topological_order_and_cycle_rejection(self) -> None:
        dag = ResearchDAG("dag_test")
        dag.add_node(DAGNode("n1", NodeType.PROPOSE, "Propose"))
        dag.add_node(DAGNode("n2", NodeType.EXECUTE_EXPERIMENT, "Exec"))
        dag.add_node(DAGNode("n3", NodeType.CRITIQUE, "Critique"))
        dag.add_edge("n1", "n2", "run")
        dag.add_edge("n2", "n3", "crit")
        self.assertEqual(dag.topological_order(), ["n1", "n2", "n3"])

        with self.assertRaises(RARPValidationError):
            dag.add_edge("n3", "n1", "illegal_cycle")
        self.assertEqual(len(dag.edges), 2)

    def test_budget_hard_ceiling_and_stop_conditions(self) -> None:
        tracker = BudgetTracker(
            BudgetSpec(max_iterations=2, max_experiments=3, max_cost_usd=0.20, cost_per_experiment_usd=0.08),
            StopConditionsSpec(max_consecutive_failures=2, patience_rounds=2),
        )
        tracker.reserve_iteration()
        tracker.reserve_experiment()  # 0.08
        tracker.reserve_experiment()  # 0.16
        with self.assertRaises(BudgetExhaustedError):
            tracker.reserve_experiment()  # 0.24 > 0.20 must be blocked before dispatch!
        snap = tracker.snapshot()
        self.assertLessEqual(snap.cost_usd_used, 0.20)
        self.assertEqual(snap.experiments_used, 2)

    def test_trial_accounting_penalizes_multiple_testing(self) -> None:
        one_trial = compute_trial_adjusted_stats(observed_sharpe=1.2, sample_bars=120, total_trials=1)
        many_trials = compute_trial_adjusted_stats(observed_sharpe=1.2, sample_bars=120, total_trials=25)
        self.assertGreater(one_trial.deflated_sharpe_ratio, many_trials.deflated_sharpe_ratio)
        self.assertLessEqual(one_trial.bonferroni_p_value, many_trials.bonferroni_p_value)

    def test_artifact_signing_detects_tampering(self) -> None:
        signer = ArtifactSigner(secret_key="unit-test-secret", key_id="unit_key")
        art = signer.sign("test_bundle", {"run_id": "r1", "sharpe": 1.25})
        self.assertTrue(signer.verify(art))

        tampered = SignedResearchArtifact(
            artifact_id=art.artifact_id,
            artifact_type=art.artifact_type,
            key_id=art.key_id,
            signed_at_utc=art.signed_at_utc,
            payload={"run_id": "r1", "sharpe": 9.99},
            payload_sha256=art.payload_sha256,
            signature_hmac_sha256=art.signature_hmac_sha256,
        )
        with self.assertRaises(ArtifactSignatureError):
            signer.verify(tampered)


if __name__ == "__main__":
    unittest.main()
