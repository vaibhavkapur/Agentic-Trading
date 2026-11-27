# ADR 0001 — TS-14 Audit, Typed Experiment DSL, and Idempotent Worker Foundation (M1)

- **Status:** Accepted
- **Milestone:** M1 — Foundation and design

## Context
`plan.md` references `Trading-Software — 14-ai-quant-research-agent` as a potential foundation, while mandating IP/licensing verification before copying external personal code, zero unrestricted generated code, strict point-in-time causality, and idempotent execution.

## Decisions
1. **Clean-Room TS-14 Adapter Seam:** Because external repository licensing and SAAT ownership terms are unresolved locally, we implement clean, documented contracts (`BacktesterAdapter`, `TS14BacktesterAdapter`, `ReferenceBacktester`) and explicitly block unvetted external copies (`allow_external=True` raises `PolicyViolationError`).
2. **Catalog-Bounded Declarative DSL:** `HypothesisSpec` and `ExperimentSpec` validate strictly against versioned `config/strategy_catalog.json`, ban code-execution tokens (`eval(`, `exec(`, `lambda`, `code`, etc.), require `signal_lag_bars >= 1`, and compute canonical semantic fingerprints.
3. **Typed Research DAG & Idempotent Workers:** `ResearchDAG` enforces acyclicity on every edge insertion. `ExperimentWorker` keys runs by `ExperimentSpec.idempotency_key()`, checkpoints `WorkerCrashError` retries, and deduplicates replays without double-charging budget.
4. **Zero-Dependency Core:** Core runtime uses Python 3.9+ standard library (`sqlite3`, `hmac`, `hashlib`, `wsgiref`) with optional extras in `pyproject.toml` for FastAPI, PostgreSQL, and S3.

## Consequences
- Clean checkouts execute deterministically with zero external network dependencies.
- Future vetted integration of TS-14 or distributed backends requires only implementing existing protocol adapters.
