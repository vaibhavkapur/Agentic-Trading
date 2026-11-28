# Earnings Call Intelligence Agent — Implementation Plan

**Project:** 41 of 67  
**Target repository:** `Trading-Agentic` (existing)  
**Suggested directory:** `projects/earnings-call-intelligence-agent/`  
**Status:** Proposed / not implemented by this plan  
**Suggested stack:** Python, Pydantic, optional LLM provider, vector search optional  
**Scope:** Independently developed educational or research prototype; offline, mock, paper or testnet execution only as applicable.

## 1. Objective and scope

Extract verifiable earnings-call claims and guidance changes with timestamped evidence.

**Primary inputs:** Public licensed or synthetic transcripts, filing timestamps, prior guidance.

**Core deliverables**

- Ingest segmented transcripts with speaker and publication metadata.
- Extract structured metrics and guidance with exact evidence spans.
- Compare current vs prior guidance and flag uncertainty.
- Evaluate extraction and citation accuracy with gold fixtures.

**Out of scope / limitations:** Financial text may contain errors or ambiguities; no automated trade action. Live capital, real customer records and production credentials are excluded. Any later production use requires a separate security, operational, legal and risk review as appropriate.

## 2. Architecture and implementation decisions

- **Boundaries:** Use typed tool contracts and evidence records; separate model calls from deterministic policy and verification. Treat retrieved text as untrusted data. Use mock tools and fixed budgets by default; no live orders or autonomous external changes.
- **Data contracts:** Define input schema, units, timestamp semantics where applicable, identifiers, validation errors and output contract in `docs/contracts.md`. Include valid, invalid and boundary fixtures.
- **Reproducibility:** Pin dependencies and configuration; version inputs and outputs; use fixed seeds for stochastic scenarios and record runtime environment. Establish a simple reference, hand-calculated fixture, or existing library oracle before adding complexity; record deviations and tolerances.
- **Integration:** Document any reusable interfaces from `Trading-Agentic` or neighboring repositories in `docs/integration.md`. Prefer independent runnable adapters over copied implementations; verify existing paths before importing. No dependency on private employer or SAAT code.
- **Delivery layout:** `src/`, `tests/`, `config/`, `data/fixtures/`, `scripts/`, `docs/`, `reports/`, dependency/build manifest. Include this `plan.md`, a project `README.md`, and documented setup, demo and validation commands. Adapt commands to the selected stack.

## 3. Implementation milestones

### M1 — Foundation and reference fixtures

- [ ] Create scaffold, dependency lock/build configuration, project README and local setup instructions.
- [ ] Define the canonical inputs (public licensed or synthetic transcripts, filing timestamps, prior guidance) and expected outputs; include schema, validation and error cases.
- [ ] Ingest segmented transcripts with speaker and publication metadata.
- [ ] Build a small deterministic fixture and an independent expected-result example; write architecture notes and the first ADR.

**Exit gate:** Clean setup and a minimal reference scenario run successfully; input and output contracts are documented and tested.

### M2 — Core domain implementation

- [ ] Extract structured metrics and guidance with exact evidence spans.
- [ ] Isolate the domain algorithm/state transitions from I/O; expose a typed library or service interface.
- [ ] Implement deterministic unit tests for: Contradictory guidance, units and fiscal periods.
- [ ] Add input validation, error propagation and explicit handling for unsupported cases; capture baseline outputs for comparison.

**Exit gate:** Core behavior passes reference fixtures, including edge cases, with no undocumented assumptions.

### M3 — Integration and evaluation

- [ ] Compare current vs prior guidance and flag uncertainty.
- [ ] Run integration scenarios covering: Prompt injection inside transcript.
- [ ] Add structured logs or diagnostic counters, replay or rerun support as appropriate, and stable output identifiers.
- [ ] Compare results against the reference baseline with a documented tolerance or evaluation protocol; retain raw outputs in `reports/`.

**Exit gate:** End-to-end demo runs reproducibly, integration fixtures pass, and discrepancies are explained.

### M4 — Hardening, benchmarking and delivery

- [ ] Evaluate extraction and citation accuracy with gold fixtures.
- [ ] Add failure or boundary scenarios for: Unanswerable questions and stale source.
- [ ] Run the acceptance checks below, record measured results and configuration, and mark untested capabilities explicitly.
- [ ] Add CI validation, operator/developer runbook, limitation notes, architecture diagram and a short demo walkthrough.

**Exit gate:** All applicable acceptance checks are evidenced; unsupported or untested features are identified; another developer can reproduce the demo from a clean checkout.

## 4. Test and validation matrix

| Test area | Required scenario | Expected evidence |
|---|---|---|
| Domain correctness | Contradictory guidance, units and fiscal periods | Reference comparison and automated assertions |
| Integration and resilience | Prompt injection inside transcript | Integration/scenario test report |
| Boundary and failure behavior | Unanswerable questions and stale source | Explicit error handling and regression test |
| Reproducibility | Same versioned inputs/configuration and fixed seed where applicable | Matching logical outputs or documented stochastic tolerance |
| Operational review | Missing configuration, unsupported inputs, restart/rerun where relevant | Clear diagnostics, documented recovery steps and no silent success |

## 5. Project-specific acceptance criteria

- [ ] Every numerical claim has evidence and normalized units.
- [ ] Report extraction F1 and citation validity.
- [ ] Abstain without support.
- [ ] All required test scenarios pass in the supported environment, or any unavailable hardware/data dependency is explicitly marked not run.
- [ ] README documents setup, demo, validation, assumptions, and known limitations; measured results distinguish actual observations from synthetic fixtures, estimates and targets.
- [ ] No real transactions, customer data, credentials or proprietary employer/SAAT artifacts in source, fixtures, logs or reports.

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

- [ ] M1–M4 completed and reviewed.
- [ ] Project-specific acceptance evidence linked from README.
- [ ] Dependency licenses and fixture provenance documented; original code and no confidential inputs.
- [ ] Reproducible example and CI workflow verified on the stated environment.
- [ ] Any production-only integrations remain disabled or explicitly outside scope.

> Numerical thresholds and technology choices in this plan are proposed engineering targets, not measured results or guarantees. Adjust them only with documented rationale and retain baseline evidence.
