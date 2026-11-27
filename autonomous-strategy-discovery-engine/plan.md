# Autonomous Strategy Discovery Engine — Implementation Plan

| Field | Value |
|---|---|
| Project | 03 of 25 |
| Classification | Extension / integration of existing portfolio foundations |
| Priority | Very high |
| Proposed owner | CTO / trading engineering (reviewers to be assigned) |
| Suggested stack | Python, NumPy, Polars, SciPy, Optuna or equivalent, existing backtester, PostgreSQL |
| Initial deployment | Local reproducible prototype, then approved paper/sandbox environment |
| Status | Proposed; not an assertion of SAAT's existing capability |

## 1. Objective and scope

Generate and evaluate candidate systematic strategies through a constrained search space and reproducible out-of-sample evaluation.

**MVP deliverables**
- Strategy DSL and catalog
- Candidate generator and constrained search
- Cost-aware walk-forward evaluator
- Multiple-testing and benchmark reports
- Strategy package export and independent review

**Explicit non-goals**
- No unconstrained code generation
- no live strategy selection based solely on backtest returns

## 2. Existing foundations and integration dependencies

- [Trading-Software — 14-ai-quant-research-agent](https://github.com/vaibhavkapur/Trading-Software/tree/main/projects/14-ai-quant-research-agent)
- [Trading-Software — 06-event-driven-backtesting-engine](https://github.com/vaibhavkapur/Trading-Software/tree/main/projects/06-event-driven-backtesting-engine)
- [Quantum-Trading — 09-quantum-strategy-optimizer](https://github.com/vaibhavkapur/Quantum-Trading/tree/main/projects/09-quantum-strategy-optimizer)

Before coding, inspect the linked repository at a pinned commit: inventory reusable contracts, tests and documented limitations. Prefer an adapter or incremental extension over duplicating the implementation. Preserve baseline tests and benchmark evidence.

**Dependencies / related plans:** #17, #18, #22; existing backtester.

Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. A linked prototype is not proof of production readiness. If access or licensing is unresolved, implement against clean, documented contracts instead.

## 3. Proposed architecture and component boundaries

| Component / workstream | Responsibility and boundary |
|---|---|
| Strategy DSL and catalog | Own the canonical domain contract and validate incoming data; publish versioned inputs. |
| Candidate generator and constrained search | Implement the core deterministic or research processing; isolate optional external dependencies. |
| Cost-aware walk-forward evaluator | Persist results or state with reproducible provenance; expose explicit failure modes. |
| Multiple-testing and benchmark reports | Expose integration or operational interfaces; apply authorization and fail-safe validation. |
| Strategy package export and independent review | Deliver reviewable evidence, operator workflow and integration tests; do not bypass approvals. |

### Suggested repository layout

```text
autonomous-strategy-discovery-engine/
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

- [x] Audit supported TS-14 signal DSL and existing backtester; define allowed strategy families and baseline.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M2 — Core implementation

- [x] Implement bounded candidate generation, immutable split manifests and transaction-cost scenarios.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M3 — Integration and validation

- [x] Add nested parameter tuning, trial accounting and robustness checks on non-overlapping periods.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

### M4 — Hardening and delivery

- [x] Deliver research leaderboard showing uncertainty and failed candidates; export approved paper candidates.
- [x] Document interfaces, assumptions and design decisions introduced in this milestone.
- [x] Add automated tests and store a reproducible demonstration or validation report.

## 5. Testing and validation

Implement unit tests for domain invariants, integration tests for adapter contracts and scenario tests for failure paths. Use fixed seeds where applicable; avoid testing only happy paths.

| Scenario | Required verification |
|---|---|
| Look-ahead injection | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Same seed rerun | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Holdout leakage | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Multiple-testing inflation | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Excessive turnover | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Cost sensitivity | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |

For quantitative work, use chronological splits, point-in-time inputs, realistic costs where relevant, and report failed experiments as well as successful ones. For execution systems, test idempotency, uncertain outcomes and state recovery. Never infer live performance from a simulated test.

## 6. Acceptance criteria / definition of done

- [x] Every trial is accounted for including failures.
- [x] Test split is untouched during candidate selection.
- [x] Baselines and candidates use identical costs and data.
- [x] Report includes uncertainty, turnover and drawdown.
- [x] Export contains exact configuration and dataset fingerprints.
- [x] A clean checkout can run the documented setup, tests and demo with permitted fixtures.
- [x] Architecture, dependency assumptions, known limitations and runbook are committed.
- [x] Relevant CI checks pass and raw evaluation or test evidence is retained.
- [x] Security, data licensing, IP and any deployment approval requirements are reviewed.

## 7. Operational controls and rollout

- Use synthetic or explicitly permitted historical data first; record provenance and entitlements.
- Store credentials outside code, separate roles, and restrict access to sensitive artifacts.
- Keep order execution disabled unless a deterministic, independently reviewed policy explicitly permits paper/sandbox operation. Any real-capital deployment is a separate approval decision requiring applicable legal/regulatory, broker, security and risk checks.
- Capture health, failure and decision metrics; document the operator response and safe fallback.
- Establish baseline measurements before setting throughput, latency, accuracy or availability targets; report environment, sample size and uncertainty rather than claiming unmeasured performance.

## 8. Handoff and evidence

Deliver source code, dependency lockfile or reproducible build instructions, architecture diagram, API/schema documentation, test report, demo script, benchmark/evaluation artifacts where applicable, and an explicit list of unsupported features. The project is complete at MVP scope only after its acceptance checklist has evidence attached.

**Next decision:** confirm the actual SAAT asset class, strategy horizon, data access, operating constraints and code ownership before selecting implementation depth or connecting real providers.
