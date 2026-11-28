# Macro Intelligence Agent — Implementation Plan

**Project:** 42 of 67  
**Target repository:** `Trading-Agentic` (existing)  
**Suggested directory:** `projects/macro-intelligence-agent/`  
**Status:** Implemented (M1–M4 completed and verified on offline synthetic fixtures; see `reports/acceptance.md`)  
**Suggested stack:** Python, Pydantic, SQLite, optional LLM  
**Scope:** Independently developed educational or research prototype; offline, mock, paper or testnet execution only as applicable.

## 1. Objective and scope

Summarize economic releases and central bank communications with revision-aware citations.

**Primary inputs:** Public/synthetic macro releases, timestamps, consensus and prior vintages.

**Core deliverables**

- Archive releases and vintages with publication gates.
- Extract figures, surprises and policy language with citations.
- Compare releases with prior vintages and generate scenario briefs.
- Evaluate against curated numerical and citation gold set.

**Out of scope / limitations:** Macro interpretations are hypotheses, not predictions; do not fabricate consensus or market impact. Live capital, real customer records and production credentials are excluded. Any later production use requires a separate security, operational, legal and risk review as appropriate.

## 2. Architecture and implementation decisions

- **Boundaries:** Use typed tool contracts and evidence records; separate model calls from deterministic policy and verification. Treat retrieved text as untrusted data. Use mock tools and fixed budgets by default; no live orders or autonomous external changes.
- **Data contracts:** Define input schema, units, timestamp semantics where applicable, identifiers, validation errors and output contract in `docs/contracts.md`. Include valid, invalid and boundary fixtures.
- **Reproducibility:** Pin dependencies and configuration; version inputs and outputs; use fixed seeds for stochastic scenarios and record runtime environment. Establish a simple reference, hand-calculated fixture, or existing library oracle before adding complexity; record deviations and tolerances.
- **Integration:** Document any reusable interfaces from `Trading-Agentic` or neighboring repositories in `docs/integration.md`. Prefer independent runnable adapters over copied implementations; verify existing paths before importing. No dependency on private employer or SAAT code.
- **Delivery layout:** `src/`, `tests/`, `config/`, `data/fixtures/`, `scripts/`, `docs/`, `reports/`, dependency/build manifest. Include this `plan.md`, a project `README.md`, and documented setup, demo and validation commands. Adapt commands to the selected stack.

## 3. Implementation milestones

### M1 — Foundation and reference fixtures

- [x] Create scaffold, dependency lock/build configuration, project README and local setup instructions.
- [x] Define the canonical inputs (public/synthetic macro releases, timestamps, consensus and prior vintages) and expected outputs; include schema, validation and error cases.
- [x] Archive releases and vintages with publication gates.
- [x] Build a small deterministic fixture and an independent expected-result example; write architecture notes and the first ADR.

**Exit gate:** Clean setup and a minimal reference scenario run successfully; input and output contracts are documented and tested.

### M2 — Core domain implementation

- [x] Extract figures, surprises and policy language with citations.
- [x] Isolate the domain algorithm/state transitions from I/O; expose a typed library or service interface.
- [x] Implement deterministic unit tests for: Embargoed release and revised data.
- [x] Add input validation, error propagation and explicit handling for unsupported cases; capture baseline outputs for comparison.

**Exit gate:** Core behavior passes reference fixtures, including edge cases, with no undocumented assumptions.

### M3 — Integration and evaluation

- [x] Compare releases with prior vintages and generate scenario briefs.
- [x] Run integration scenarios covering: Unit mismatch and conflicting reports.
- [x] Add structured logs or diagnostic counters, replay or rerun support as appropriate, and stable output identifiers.
- [x] Compare results against the reference baseline with a documented tolerance or evaluation protocol; retain raw outputs in `reports/`.

**Exit gate:** End-to-end demo runs reproducibly, integration fixtures pass, and discrepancies are explained.

### M4 — Hardening, benchmarking and delivery

- [x] Evaluate against curated numerical and citation gold set.
- [x] Add failure or boundary scenarios for: Untrusted source instructions.
- [x] Run the acceptance checks below, record measured results and configuration, and mark untested capabilities explicitly.
- [x] Add CI validation, operator/developer runbook, limitation notes, architecture diagram and a short demo walkthrough.

**Exit gate:** All applicable acceptance checks are evidenced; unsupported or untested features are identified; another developer can reproduce the demo from a clean checkout.

## 4. Test and validation matrix

| Test area | Required scenario | Expected evidence |
|---|---|---|
| Domain correctness | Embargoed release and revised data | Reference comparison and automated assertions |
| Integration and resilience | Unit mismatch and conflicting reports | Integration/scenario test report |
| Boundary and failure behavior | Untrusted source instructions | Explicit error handling and regression test |
| Reproducibility | Same versioned inputs/configuration and fixed seed where applicable | Matching logical outputs or documented stochastic tolerance |
| Operational review | Missing configuration, unsupported inputs, restart/rerun where relevant | Clear diagnostics, documented recovery steps and no silent success |

## 5. Project-specific acceptance criteria

- [x] No future release visible at historical cutoff.
- [x] All figures traceable.
- [x] Report exact-match and abstention metrics.
- [x] All required test scenarios pass in the supported environment, or any unavailable hardware/data dependency is explicitly marked not run.
- [x] README documents setup, demo, validation, assumptions, and known limitations; measured results distinguish actual observations from synthetic fixtures, estimates and targets.
- [x] No real transactions, customer data, credentials or proprietary employer/SAAT artifacts in source, fixtures, logs or reports.

## 6. Required final evidence

| Artifact | Purpose |
|---|---|
| `README.md` | Overview, quickstart, example output and limitations |
| `docs/architecture.md` | Component diagram, data flow, invariants and trade-offs |
| `docs/contracts.md` | Input/output schemas, units, versions and errors |
| `docs/integration.md` | Adapter boundaries, dependencies and compatibility |
| `docs/runbook.md` | Demo, validation, diagnostics and recovery instructions |
| `tests/` | Unit, integration and required failure scenarios |
| `reports/acceptance.md` | Each acceptance criterion mapped to test or benchmark evidence |
| `reports/` raw results | Versioned machine-readable outputs and runtime/configuration metadata |

## 7. Completion checklist

- [x] M1–M4 completed and reviewed.
- [x] Project-specific acceptance evidence linked from README.
- [x] Dependency licenses and fixture provenance documented; original code and no confidential inputs.
- [x] Reproducible example and CI workflow verified on the stated environment.
- [x] Any production-only integrations remain disabled or explicitly outside scope.

> Numerical thresholds and technology choices in this plan are proposed engineering targets, not measured results or guarantees. Adjust them only with documented rationale and retain baseline evidence.
