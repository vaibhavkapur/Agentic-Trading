# Financial Research Agent — Implementation Plan

| Field | Value |
|---|---|
| Project | 04 of 25 |
| Classification | New capability |
| Priority | High |
| Proposed owner | CTO / trading engineering (reviewers to be assigned) |
| Suggested stack | Python, FastAPI, document parser, PostgreSQL, object storage, optional LLM API |
| Initial deployment | Local reproducible prototype, then approved paper/sandbox environment |
| Status | Proposed; not an assertion of SAAT's existing capability |

## 1. Objective and scope

Produce evidence-linked research briefs on companies, macroeconomic events and fundamentals using permitted source documents.

**MVP deliverables**
- Issuer and instrument resolver
- Filing/news ingestion and parsing
- Structured financial facts with provenance
- Citation-grounded research workflow
- Analyst review interface

**Explicit non-goals**
- No automatic trade execution
- no access to unlicensed feeds
- no invented facts

## 2. Existing foundations and integration dependencies

- Greenfield capability in the prior GitHub coverage audit. Reuse common contracts and fixtures only after checking ownership and compatibility.

Start with a small independently runnable vertical slice. Do not create duplicate backtesters, order managers, ledgers or data ingestion services when a reviewed shared interface already exists.

**Dependencies / related plans:** #17, #19, #6.

Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. A linked prototype is not proof of production readiness. If access or licensing is unresolved, implement against clean, documented contracts instead.

## 3. Proposed architecture and component boundaries

| Component / workstream | Responsibility and boundary |
|---|---|
| Issuer and instrument resolver | Own the canonical domain contract and validate incoming data; publish versioned inputs. |
| Filing/news ingestion and parsing | Implement the core deterministic or research processing; isolate optional external dependencies. |
| Structured financial facts with provenance | Persist results or state with reproducible provenance; expose explicit failure modes. |
| Citation-grounded research workflow | Expose integration or operational interfaces; apply authorization and fail-safe validation. |
| Analyst review interface | Deliver reviewable evidence, operator workflow and integration tests; do not bypass approvals. |

### Suggested repository layout

```text
financial-research-agent/
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

- [ ] Build document ingestion for a small licensed or public-source fixture corpus; preserve publication and retrieval timestamps.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M2 — Core implementation

- [ ] Extract financial statement facts, units, currency, periods and revisions; resolve issuer identifiers.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M3 — Integration and validation

- [ ] Implement constrained question answering and research briefs with citation verification and abstention.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M4 — Hardening and delivery

- [ ] Evaluate factual accuracy, stale documents, source conflicts and analyst review; publish a reproducible demo.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

## 5. Testing and validation

Implement unit tests for domain invariants, integration tests for adapter contracts and scenario tests for failure paths. Use fixed seeds where applicable; avoid testing only happy paths.

| Scenario | Required verification |
|---|---|
| Wrong issuer | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Restated filing | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Unit/currency error | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Conflicting facts | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Missing source | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Prompt injection in document | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |

For quantitative work, use chronological splits, point-in-time inputs, realistic costs where relevant, and report failed experiments as well as successful ones. For execution systems, test idempotency, uncertain outcomes and state recovery. Never infer live performance from a simulated test.

## 6. Acceptance criteria / definition of done

- [ ] Every factual research claim links to a source and page or passage.
- [ ] Facts preserve as-of timestamp, unit and currency.
- [ ] Missing or conflicting evidence is surfaced.
- [ ] No unsupported price targets.
- [ ] Repeated fixture queries reproduce evidence links.
- [ ] A clean checkout can run the documented setup, tests and demo with permitted fixtures.
- [ ] Architecture, dependency assumptions, known limitations and runbook are committed.
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
