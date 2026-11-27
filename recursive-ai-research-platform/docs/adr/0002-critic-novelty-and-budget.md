# ADR 0002 — Evidence-Linked Critic, Novelty Checks, and Hard Budget Enforcement (M2)

- **Status:** Accepted
- **Milestone:** M2 — Core implementation

## Context
LLM-assisted or automated research loops can fabricate metrics, waste compute repeating near-identical hypotheses, or overshoot budget ceilings when failures occur.

## Decisions
1. **Cryptographically Evidence-Linked Critic:** Every `CriticReport` must contain explicit `MetricClaim(run_id, metric_name, claimed_value, artifact_sha256)` items. `ResearchCritic.verify_claims()` cross-checks every claim against the immutable `RunRegistry` within `metric_tolerance` (`1e-9`) before persisting or accepting the report. Violations raise `HallucinatedMetricError` and write a `HALLUCINATED_METRIC_DETECTED` audit event.
2. **Exact & Near-Duplicate Novelty Filtering:** `ResearchMemory.check_novelty()` blocks exact `semantic_fingerprint` matches and near-duplicates whose normalized L1 parameter distance falls below `near_duplicate_distance` before experiment budget is charged.
3. **Pre-Dispatch Atomic Budget Reservation:** `BudgetTracker.reserve_iteration()` and `reserve_experiment()` check ceilings atomically *before* execution so configured iteration, experiment, USD cost, compute, and token limits cannot be exceeded.

## Consequences
- Hallucinated or ungrounded critic reports can never enter the registry or reach human review.
- Budget overspend is structurally prevented even under retries or loop errors.
