# ADR 0003 — Iterative Refinement, Negative-Result Memory, Trial Accounting, and Blinded Holdout (M3)

- **Status:** Accepted
- **Milestone:** M3 — Integration and validation

## Context
Iterative search without negative-result tracking, multiple-testing accounting, or holdout isolation suffers from survivorship bias and data snooping.

## Decisions
1. **Permanent Negative-Result Memory:** Failed, leakage-rejected, and critic-rejected hypotheses are stored in `ResearchMemory` and `RunRegistry` and remain queryable via `failed_hypotheses(...)` and `/api/memory/hypotheses?failed_only=true`.
2. **Multiple-Testing Trial Accounting:** Every attempted trial (including failures and rejections) increments the denominator used to compute Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR), and Bonferroni-adjusted p-values attached to every `CriticReport`.
3. **Blinded HoldoutGuard:** Chronological splits enforce `embargo_bars >= 1` between `train`, `validation`, and `holdout`. Automated workers and refiners receive only `train` and `validation`; reading `holdout` raises `HoldoutAccessError` unless presented with a single-use cryptographic `HoldoutReleaseToken` issued by an independent reviewer (`reviewer_id != proposer_id`). Every access attempt (granted or denied) is logged.
4. **Bounded Iterative Refiner:** `HypothesisRefiner` generates lineage-linked child hypotheses (`parent_hypothesis_id`, `generation + 1`) guided by critic finding codes while validating every proposal against `StrategyCatalog` and `ResearchMemory.check_novelty()`.

## Consequences
- Overfitting pressure from repeated refinement is explicitly surfaced to human reviewers via DSR and full negative-result history.
- Holdout leakage during automated search is prevented by construction.
