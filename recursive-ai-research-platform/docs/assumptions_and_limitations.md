# Assumptions, Known Limitations, Security & IP Review

## Dependency & Foundation Audit (TS-14)

- **Referenced Foundation:** `Trading-Software — 14-ai-quant-research-agent` (`plan.md` §2).
- **IP & Access Review Status:** Access, license terms, background IP, and SAAT ownership terms for the external personal repository are **not yet confirmed** in this offline workspace. Per `plan.md` §2 ("If access or licensing is unresolved, implement against clean, documented contracts instead"), no external repository code was copied.
- **Integration Boundary:** `TS14BacktesterAdapter` in `src/rarp/scheduler/backtester.py` provides a clean-room contract seam delegating to `ReferenceBacktester`, and explicitly raises `PolicyViolationError` if `allow_external=True` is requested prior to legal/IP sign-off.

## Core Assumptions

1. **Synthetic Data Only (MVP):** All local tests and demos run on deterministic synthetic daily multi-regime equities (`SYN_EQ_A`, `SYN_EQ_B`, `SYN_EQ_C`) with explicit `PERMITTED_INTERNAL_RESEARCH_SYNTHETIC` entitlement. No licensed vendor data is included.
2. **Causal Daily Bar Model:** Signals computed at bar `t` execute with a strict minimum lag `signal_lag_bars >= 1`, evaluated bar-by-bar with explicit commission, half-spread, slippage, and short-borrow costs in USD.
3. **Statistical Honesty:** DSR and Bonferroni adjustments assume approximate IID normal returns as a conservative first-order screening penalty; non-normal skewness/kurtosis and regime shifts require human review before any sandbox deployment.
4. **No Alpha Claim:** Passing validation tests or demo runs proves architectural auditability, determinism, and governance controls — **never** live trading profitability.

## Explicit List of Unsupported Features (Non-Goals & Future Work)

- **No automatic live deployment or real-capital order routing** (`LIVE` target is hard-blocked with `PolicyViolationError`; `order_execution_enabled` defaults to `false`).
- **No unrestricted LLM code generation or arbitrary Python execution** (only catalog-bounded declarative DSL hypotheses are accepted).
- **No external network LLM provider calls in the default deterministic prototype** (`CriticAdapter` and `RefinerAdapter` protocols are provided for future vetted LLM adapters, with mandatory claim verification).
- **No distributed Kubernetes/Celery queue or multi-node PostgreSQL/S3 deployment in MVP** (clean `ObjectStore` and `RunRegistry` seams are ready when infrastructure is provisioned).
- **No intraday tick/order-book microstructure simulation** (bar-level daily simulation only).

## Security, Credentials & Governance Controls

- **Zero Secrets in Code or Config:** `config/*.json` contain only non-sensitive parameters. `ArtifactSigner` reads signing keys from `RARP_SIGNING_KEY` or caller injection (defaulting to ephemeral CSPRNG keys locally).
- **Separation of Duties:** `PromotionGate` rejects self-approval (`reviewer_id == proposer_id`) and automated agent reviewer IDs (`auto_*`, `agent_*`).
- **Append-Only Immutability:** SQLite triggers prevent `UPDATE`/`DELETE` on `runs`, `critic_reports`, `review_decisions`, and `audit_events`, complemented by a SHA-256 hash chain (`verify_hash_chain()`) and append-only `audit_log.jsonl`.
- **Blinded Holdout Protection:** Automated search/refinement loops receive only `train` and `validation` splits; holdout access requires a single-use cryptographic token issued by an independent reviewer.
