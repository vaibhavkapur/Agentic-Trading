# ADR-001: Deterministic Policy Separation, Offline Contracts, and Hash-Bound Governance

- **Status:** Accepted
- **Date:** 2026-11-28
- **Context:** Project 43 (`ai-investment-committee`) requires evidence-based Bull, Bear, Portfolio, and Independent Risk reviews for paper proposals with deterministic risk vetoes, human approval bound to proposal hash, and full replayability.

## Decisions

### 1. Strict Separation of Agent Reasoning and Deterministic Risk Policy
- **Decision:** All numerical risk checks (`MAX_SINGLE_POSITION_WEIGHT_PCT`, `MAX_SECTOR_WEIGHT_PCT`, `MAX_GROSS_EXPOSURE_PCT`, `MIN_CASH_RESERVE_PCT`, `MAX_ESTIMATED_VAR_95_PCT`, `MAX_ADV_PARTICIPATION_PCT`, `RESTRICTED_TICKER`, `NO_LIVE_EXECUTION`) and citation integrity checks (`MAX_FABRICATED_CITATIONS`, `MIN_VERIFIED_CITATION_RATIO`) run in pure Python (`risk_engine.py`) with zero LLM involvement.
- **Consequence:** Prompt injections embedded in research briefs or overconfident agent narratives cannot weaken risk limits or bypass a `VETO`.

### 2. Zero-Dependency Typed Contracts with Pydantic-Compatible Interface
- **Decision:** While `plan.md` suggests Python + Pydantic + SQLite (noting technology choices may be adjusted with documented rationale), the target offline execution environment provides Python `3.9.6` and `sqlite3 3.51.0` without preinstalled third-party packages. We therefore implemented immutable frozen-dataclass contracts in `models.py` exposing `model_validate()` and `model_dump()` with strict runtime type, range, currency, enum, and UTC ISO-8601 validation, while retaining `pydantic>=2.7,<3.0` as an optional extra in `pyproject.toml`.
- **Consequence:** Any developer can run the full test suite, demo, CLI, and replay from a clean checkout using only standard Python `3.9+` with zero network access. Future Pydantic v2 model wrappers can map 1:1 to `model_validate()` / `model_dump()`.

### 3. Canonical SHA-256 Hashing and SQLite Replay Store
- **Decision:** Proposals and configurations are serialized via sorted-key canonical JSON (`hashing.py`) and hashed with SHA-256. Every deliberation persists the full `DeliberationReplayTrace`, canonical proposal JSON, versioned config JSON, and budget usage in SQLite (`storage.py`), with `UNIQUE(decision_id)` and `PRIMARY KEY(approval_id)` constraints on `human_approvals`.
- **Consequence:** Proposal tampering invalidates human approval (`ProposalHashMismatchError`), duplicate approvals fail both in-memory and across process restarts (`DuplicateApprovalError`), and deliberations replay deterministically.
