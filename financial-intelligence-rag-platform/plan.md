# Financial Intelligence RAG Platform — Implementation Plan

| Field | Value |
|---|---|
| Project | 06 of 25 |
| Classification | New capability |
| Priority | High |
| Proposed owner | CTO / trading engineering (reviewers to be assigned) |
| Suggested stack | Python, FastAPI, PostgreSQL/pgvector or equivalent, object storage, embedding and reranking adapters |
| Initial deployment | Local reproducible prototype, then approved paper/sandbox environment |
| Status | Proposed; not an assertion of SAAT's existing capability |

**Local implementation evidence:** [Acceptance record](reports/acceptance.md) · [Setup and demo](README.md)

## 1. Objective and scope

Create a permission-aware, point-in-time retrieval system for filings, market research and internal investment documents.

**MVP deliverables**
- Document store and versioned chunks
- Hybrid keyword/vector index
- Metadata and access filters
- Evidence-grounded answer generation
- Retrieval and citation evaluation suite

**Explicit non-goals**
- No confidential data sent to external providers without approval
- no automatic trading decisions

## 2. Existing foundations and integration dependencies

- Greenfield capability in the prior GitHub coverage audit. Reuse common contracts and fixtures only after checking ownership and compatibility.

Start with a small independently runnable vertical slice. Do not create duplicate backtesters, order managers, ledgers or data ingestion services when a reviewed shared interface already exists.

**Dependencies / related plans:** #4, #17, #19.

Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. A linked prototype is not proof of production readiness. If access or licensing is unresolved, implement against clean, documented contracts instead.

## 3. Proposed architecture and component boundaries

| Component / workstream | Responsibility and boundary |
|---|---|
| Document store and versioned chunks | Own the canonical domain contract and validate incoming data; publish versioned inputs. |
| Hybrid keyword/vector index | Implement the core deterministic or research processing; isolate optional external dependencies. |
| Metadata and access filters | Persist results or state with reproducible provenance; expose explicit failure modes. |
| Evidence-grounded answer generation | Expose integration or operational interfaces; apply authorization and fail-safe validation. |
| Retrieval and citation evaluation suite | Deliver reviewable evidence, operator workflow and integration tests; do not bypass approvals. |

### Suggested repository layout

```text
financial-intelligence-rag-platform/
  plan.md
  README.md
  docs/              # architecture, ADRs, assumptions, runbook
  src/               # domain contracts, core logic, adapters
  config/            # versioned settings; no secrets
  data/fixtures/     # permitted or synthetic inputs and manifests
  tests/unit/
  tests/integration/
  tests/scenarios/
  scripts/           # setup, demo, reproduce, validate
  reports/           # evaluation, benchmarks, acceptance evidence
```

Adapt the directory layout to the language and existing repository. Define domain types and schemas before choosing a distributed deployment; start with the simplest process boundaries that satisfy the workload. Use stable identifiers, explicit units/currency where relevant, UTC event and availability timestamps, versioned configuration and structured errors. Separate external provider interfaces from business logic.

## 4. Implementation milestones

Milestones are ordered by dependency, not promised calendar dates. Each milestone ends with a runnable demo and passing relevant tests.

### M1 — Foundation and design

- [x] Define corpus, access model and document version schema; ingest sample documents with immutable hashes.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M2 — Core implementation

- [x] Implement chunking, keyword and dense retrieval, metadata filters and reranker.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M3 — Integration and validation

- [x] Build citation-first answer synthesis, abstention and source comparison.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M4 — Hardening and delivery

- [x] Measure retrieval recall and citation support; test access controls, deleted content and as-of restrictions.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

## 5. Testing and validation

Implement unit tests for domain invariants, integration tests for adapter contracts and scenario tests for failure paths. Use fixed seeds where applicable; avoid testing only happy paths.

| Scenario | Required verification |
|---|---|
| Cross-tenant retrieval | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Stale filing | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Future-document leakage | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Malicious embedded instructions | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Unanswerable question | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Deletion propagation | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |

For quantitative work, use chronological splits, point-in-time inputs, realistic costs where relevant, and report failed experiments as well as successful ones. For execution systems, test idempotency, uncertain outcomes and state recovery. Never infer live performance from a simulated test.

## 6. Acceptance criteria / definition of done

- [x] Retrieved sources satisfy document permissions and as-of filters.
- [x] Every answer citation resolves to the exact version and passage.
- [x] Evaluation reports recall@k and supported-claim rate.
- [x] No answer is fabricated when evidence is missing.
- [x] Index can be rebuilt from manifest.
- [x] A clean checkout can run the documented setup, tests and demo with permitted fixtures.
- [x] Architecture, dependency assumptions, known limitations and runbook are committed.
- [ ] Relevant CI checks pass and raw evaluation or test evidence is retained.
- [ ] Security, data licensing, IP and any deployment approval requirements are reviewed.

## 7. Operational controls and rollout

- Use synthetic or explicitly permitted historical data first; record provenance and entitlements.
- Store credentials outside code, separate roles, and restrict access to sensitive artifacts.
- Keep order execution disabled unless a deterministic, independently reviewed policy explicitly permits paper/sandbox operation. Any real-capital deployment is a separate approval decision requiring applicable legal/regulatory, broker, security and risk checks.
- Capture health, failure and decision metrics; document the operator response and safe fallback.
- Establish baseline measurements before setting throughput, latency, accuracy or availability targets; report environment, sample size and uncertainty rather than claiming unmeasured performance.

## 8. Handoff and evidence

Deliver source code, dependency lockfile or reproducible build instructions, architecture diagram, API/schema documentation, test report, demo script, benchmark/evaluation artifacts where applicable, and an explicit list of unsupported features. The project is complete at MVP scope only after its acceptance checklist has evidence attached.

**Next decision:** confirm the actual SAAT asset class, strategy horizon, data access, operating constraints and code ownership before selecting implementation depth or connecting real providers.
