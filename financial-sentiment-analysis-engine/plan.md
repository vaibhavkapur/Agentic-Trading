# Financial Sentiment Analysis Engine — Implementation Plan

| Field | Value |
|---|---|
| Project | 05 of 25 |
| Classification | New capability |
| Priority | High |
| Proposed owner | CTO / trading engineering (reviewers to be assigned) |
| Suggested stack | Python, PyTorch, scikit-learn, transformers, Polars, FastAPI |
| Initial deployment | Local reproducible prototype, then approved paper/sandbox environment |
| Status | Local synthetic MVP implemented and validated. Organizational review pending. |

## 1. Objective and scope

Convert timestamped financial text into calibrated, entity-specific sentiment features for downstream research.

**MVP deliverables**
- Text and entity normalization
- Labeled evaluation corpus
- Lexicon and classifier baselines
- Calibration and aggregation service
- Sentiment feature feed and evaluation dashboard

**Explicit non-goals**
- No claim that positive sentiment implies a profitable trade
- no scraping outside source terms

## 2. Existing foundations and integration dependencies

- Greenfield capability in the prior GitHub coverage audit. Reuse common contracts and fixtures only after checking ownership and compatibility.

Start with a small independently runnable vertical slice. Do not create duplicate backtesters, order managers, ledgers or data ingestion services when a reviewed shared interface already exists.

**Dependencies / related plans:** #19, #18, #23.

Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. A linked prototype is not proof of production readiness. If access or licensing is unresolved, implement against clean, documented contracts instead.

## 3. Proposed architecture and component boundaries

| Component / workstream | Responsibility and boundary |
|---|---|
| Text and entity normalization | Own the canonical domain contract and validate incoming data; publish versioned inputs. |
| Labeled evaluation corpus | Implement the core deterministic or research processing; isolate optional external dependencies. |
| Lexicon and classifier baselines | Persist results or state with reproducible provenance; expose explicit failure modes. |
| Calibration and aggregation service | Expose integration or operational interfaces; apply authorization and fail-safe validation. |
| Sentiment feature feed and evaluation dashboard | Deliver reviewable evidence, operator workflow and integration tests; do not bypass approvals. |

### Suggested repository layout

```text
financial-sentiment-analysis-engine/
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

- [x] Define labels for positive, negative, neutral and uncertain; create an annotated permitted dataset and chronological split.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M2 — Core implementation

- [x] Build lexicon and supervised baselines, entity linking and deduplication.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M3 — Integration and validation

- [x] Train or adapt financial text model; calibrate scores and aggregate by issuer and time window.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M4 — Hardening and delivery

- [x] Publish time-aware evaluation, drift metrics and feature API; compare against non-text baseline.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

## 5. Testing and validation

Implement unit tests for domain invariants, integration tests for adapter contracts and scenario tests for failure paths. Use fixed seeds where applicable; avoid testing only happy paths.

| Scenario | Required verification |
|---|---|
| Duplicate syndicated articles | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Headline/body disagreement | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Entity ambiguity | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Sarcasm | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Late article | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Data leakage | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |

For quantitative work, use chronological splits, point-in-time inputs, realistic costs where relevant, and report failed experiments as well as successful ones. For execution systems, test idempotency, uncertain outcomes and state recovery. Never infer live performance from a simulated test.

## 6. Acceptance criteria / definition of done

- [x] Chronological test split and annotation rules are versioned.
- [x] Model report includes macro-F1 and calibration against baseline.
- [x] Duplicates do not inflate aggregation.
- [x] Features expose event and availability timestamps.
- [x] Uncertain text can abstain.
- [x] A clean checkout can run the documented setup, tests and demo with permitted fixtures.
- [x] Architecture, dependency assumptions, known limitations and runbook are committed.
- [x] The local CI entry point passes and raw evidence is retained. Hosted CI awaits a remote run.
- [x] Local controls, synthetic-data provenance, IP assumptions and deployment approval requirements are documented in the runbook. External sign-off is pending.

## 7. Operational controls and rollout

- Use synthetic or explicitly permitted historical data first; record provenance and entitlements.
- Store credentials outside code, separate roles, and restrict access to sensitive artifacts.
- Keep order execution disabled unless a deterministic, independently reviewed policy explicitly permits paper/sandbox operation. Any real-capital deployment is a separate approval decision requiring applicable legal/regulatory, broker, security and risk checks.
- Capture health, failure and decision metrics; document the operator response and safe fallback.
- Establish baseline measurements before setting throughput, latency, accuracy or availability targets; report environment, sample size and uncertainty rather than claiming unmeasured performance.

## 8. Handoff and evidence

Deliver source code, dependency lockfile or reproducible build instructions, architecture diagram, API/schema documentation, test report, demo script, benchmark/evaluation artifacts where applicable, and an explicit list of unsupported features. The project is complete at MVP scope only after its acceptance checklist has evidence attached.

**Next decision:** confirm the actual SAAT asset class, strategy horizon, data access, operating constraints and code ownership before selecting implementation depth or connecting real providers.

## Local implementation evidence

The local MVP is implemented. See the [milestone and acceptance evidence](reports/findings.md), [reproduction instructions](README.md), [raw evaluation](reports/evaluation.json), and [validation transcript](reports/validation.txt). The [runbook](docs/runbook.md) records the local security, fixture provenance, IP assumptions and deployment boundary. External ownership confirmation, hosted CI and deployment approvals remain pending.
