# ADR-002: Deterministic Policy Authority & Exact-Action Hash-Bound Approvals

- **Status:** Accepted
- **Date:** 2026-11-27

## Context
Multi-agent trading architectures face prompt injection, conflicting agent theses, and confused-deputy risks where an agent or compromised prompt attempts to alter order size, symbol, or execution mode after review.

## Decision
1. Keep deterministic `PolicyEngine` and `IndependentRiskService` outside agent control as the final authority.
2. Bind every `ApprovalRequest` to a canonical SHA-256 `exact_action_hash` computed over all executable fields (`account_id`, `symbol`, `side`, `quantity`, `order_type`, `limit_price`, `time_in_force`, `currency`, `policy_version`, `proposal_id`).
3. Enforce strict TTL expiration (`approval_ttl_seconds`), RBAC role allowlist (`RISK_OFFICER`, `TRADING_SUPERVISOR`, `PORTFOLIO_APPROVER`), maker-checker separation, and single-use `CONSUMED` state transition.

## Consequences
- Any post-approval parameter mutation fails with `APPROVAL_PARAMETER_MISMATCH`.
- Replaying a consumed approval fails with `APPROVAL_ALREADY_CONSUMED`.
- Expired approvals fail closed with `APPROVAL_EXPIRED`.
