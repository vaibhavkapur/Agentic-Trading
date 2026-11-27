# Reinforcement Learning Trading Engine — Implementation Plan

| Field | Value |
|---|---|
| Project | 07 of 25 |
| Classification | New capability |
| Priority | Medium |
| Proposed owner | CTO / trading engineering (reviewers to be assigned) |
| Suggested stack | Python, Gymnasium, PyTorch, Stable-Baselines3 or equivalent, NumPy |
| Initial deployment | Local reproducible prototype, then approved paper/sandbox environment |
| Status | Proposed; not an assertion of SAAT's existing capability |

## 1. Objective and scope

Evaluate reinforcement-learning allocation or execution policies in controlled simulation against simple classical benchmarks.

**MVP deliverables**
- Gym-compatible market environment
- Explicit observation/action/reward specification
- Cost and risk model
- Baseline and RL trainers
- Walk-forward evaluation and policy report

**Explicit non-goals**
- No online learning with real capital
- no profitability claim from simulation

## 2. Existing foundations and integration dependencies

- Greenfield capability in the prior GitHub coverage audit. Reuse common contracts and fixtures only after checking ownership and compatibility.

Start with a small independently runnable vertical slice. Do not create duplicate backtesters, order managers, ledgers or data ingestion services when a reviewed shared interface already exists.

**Dependencies / related plans:** #17, #18, existing backtester and simulator.

Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. A linked prototype is not proof of production readiness. If access or licensing is unresolved, implement against clean, documented contracts instead.

## 3. Proposed architecture and component boundaries

| Component / workstream | Responsibility and boundary |
|---|---|
| Gym-compatible market environment | Own the canonical domain contract and validate incoming data; publish versioned inputs. |
| Explicit observation/action/reward specification | Implement the core deterministic or research processing; isolate optional external dependencies. |
| Cost and risk model | Persist results or state with reproducible provenance; expose explicit failure modes. |
| Baseline and RL trainers | Expose integration or operational interfaces; apply authorization and fail-safe validation. |
| Walk-forward evaluation and policy report | Deliver reviewable evidence, operator workflow and integration tests; do not bypass approvals. |

### Suggested repository layout

```text
reinforcement-learning-trading-engine/
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

- [ ] Choose one bounded task (allocation or execution); define causal observations, action limits, cost model and seeded environment.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M2 — Core implementation

- [ ] Implement random, buy-and-hold or heuristic baseline appropriate to task; test accounting and reward conservation.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M3 — Integration and validation

- [ ] Train selected policy with fixed compute budgets and chronological validation; log every run.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M4 — Hardening and delivery

- [ ] Evaluate held-out periods and stress scenarios, compare baselines with uncertainty, export paper-only policy artifact.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

## 5. Testing and validation

Implement unit tests for domain invariants, integration tests for adapter contracts and scenario tests for failure paths. Use fixed seeds where applicable; avoid testing only happy paths.

| Scenario | Required verification |
|---|---|
| Future observation | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Reward hacking | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Unbounded actions | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Unrealistic fills | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Seed reproducibility | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Regime shift | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Transaction cost sensitivity | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |

For quantitative work, use chronological splits, point-in-time inputs, realistic costs where relevant, and report failed experiments as well as successful ones. For execution systems, test idempotency, uncertain outcomes and state recovery. Never infer live performance from a simulated test.

## 6. Acceptance criteria / definition of done

- [ ] No observations contain future data.
- [ ] Environment balances cash, holdings and costs.
- [ ] All policies use identical evaluation scenarios.
- [ ] Evaluation reports return/risk or execution-cost metrics plus uncertainty.
- [ ] Policy cannot exceed deterministic action limits.
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
