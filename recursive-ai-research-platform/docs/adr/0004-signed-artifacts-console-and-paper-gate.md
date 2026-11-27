# ADR 0004 — Signed Research Artifacts, Review Console, and Paper-Only Promotion Gate (M4)

- **Status:** Accepted
- **Milestone:** M4 — Hardening and delivery

## Context
`plan.md` requires independent human approval for promotion, signed research artifacts, reproducibility verification, a review console, and strict prohibition of automatic live deployment.

## Decisions
1. **HMAC-SHA256 Signed Bundles:** `ArtifactSigner` signs canonical JSON payloads using externally provided keys (`RARP_SIGNING_KEY` or caller-supplied; ephemeral locally, never hardcoded). Tampering with payload or signature raises `ArtifactSignatureError`.
2. **Strict Separation of Duties & Paper-Only Target:** `PromotionGate` enforces:
   - `target_environment == "PAPER_SANDBOX"` (`LIVE` or any other target raises `PolicyViolationError`).
   - `reviewer_id != proposer_id` and non-automated reviewer identity (`ReviewGateError` otherwise).
   - Verified `CriticReport` and valid artifact signature present.
   - Emitted `PaperSandboxPackage` defaults to `order_execution_enabled=False` and `live_deployment_prohibited=True`.
3. **Review Console:** `ReviewConsoleService` powers both a zero-dependency WSGI HTML/JSON console (`rarp serve-console`) and an optional FastAPI factory (`create_fastapi_app`).
4. **Deterministic Replay Verification:** `verify_deterministic_reproducibility()` executes the full loop twice from clean state directories and verifies metric differences `<= 1e-12`.

## Consequences
- No automated agent or proposer can self-approve a strategy or promote directly to live trading.
- Reviewers inspect immutable, hash-chained, cryptographically signed evidence bundles before issuing a paper-sandbox decision.
