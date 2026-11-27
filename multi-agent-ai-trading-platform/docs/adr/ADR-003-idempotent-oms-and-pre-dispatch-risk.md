# ADR-003: Idempotent OMS Dispatch & Mandatory Pre-Dispatch Risk Re-Validation

- **Status:** Accepted
- **Date:** 2026-11-27

## Context
Market conditions, quote freshness, and account cash/exposures can change between the moment a proposal is created/approved and the moment an order is dispatched. Furthermore, network retries, broker timeouts, and duplicate fill notifications can cause double execution or corrupted position accounting.

## Decision
1. Require `IndependentRiskService.evaluate(..., stage="PRE_DISPATCH")` inside `IdempotentOMS.dispatch_approved_order` immediately before consuming an approval or submitting to the paper broker.
2. Require a unique `idempotency_key` mapped deterministically to `client_order_id` (`UNIQUE` in persistence). Duplicate dispatch requests return the existing `OrderRecord`, and retries on `UNCERTAIN_TIMEOUT` orders reconcile against the broker via `query_by_client_order_id` rather than re-submitting blindly.
3. Deduplicate execution fills via a `UNIQUE` constraint on `broker_fill_id` (`save_fill_if_new`) before mutating account cash or positions.

## Consequences
- Stale quotes or exposure drift occurring after human approval still fail closed prior to broker submission.
- Duplicate dispatch messages, timeout retries, and duplicate fill webhooks never create duplicate orders or double-counted positions.
