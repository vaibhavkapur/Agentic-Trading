# Multi-Agent AI Trading Platform — Implementation Plan

| Field | Value |
|---|---|
| Project | 02 of 25 |
| Classification | Extension / integration of existing portfolio foundations |
| Priority | Very high |
| Proposed owner | CTO / trading engineering (reviewers to be assigned) |
| Suggested stack | Python, FastAPI, typed schemas, PostgreSQL, event bus, optional LangGraph or equivalent |
| Initial deployment | Local reproducible prototype, then approved paper/sandbox environment |
| Status | Proposed; not an assertion of SAAT's existing capability |

## 1. Objective and scope

Coordinate research, portfolio, risk and execution services through typed proposals while deterministic policy remains the final authority.

**MVP deliverables**
- Research, portfolio and risk agent adapters
- Orchestrator with bounded tool calls
- Shared state and decision provenance
- Deterministic policy and exact-action approvals
- Paper broker integration and operator console

**Explicit non-goals**
- No agent-controlled override of exposure controls
- no live trading by default

## 2. Existing foundations and integration dependencies

- [Trading-Software — 01-agentic-trading-platform](https://github.com/vaibhavkapur/Trading-Software/tree/main/projects/01-agentic-trading-platform)
- [Trading-Software — 15-agentic-trading-guardrails](https://github.com/vaibhavkapur/Trading-Software/tree/main/projects/15-agentic-trading-guardrails)
- [Trading-Software — 14-ai-quant-research-agent](https://github.com/vaibhavkapur/Trading-Software/tree/main/projects/14-ai-quant-research-agent)

Before coding, inspect the linked repository at a pinned commit: inventory reusable contracts, tests and documented limitations. Prefer an adapter or incremental extension over duplicating the implementation. Preserve baseline tests and benchmark evidence.

**Dependencies / related plans:** #1, #9, #10, #13, #22; existing OMS and pre-trade risk engine.

Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. A linked prototype is not proof of production readiness. If access or licensing is unresolved, implement against clean, documented contracts instead.

## 3. Proposed architecture and component boundaries

| Component / workstream | Responsibility and boundary |
|---|---|
| Research, portfolio and risk agent adapters | Own the canonical domain contract and validate incoming data; publish versioned inputs. |
| Orchestrator with bounded tool calls | Implement the core deterministic or research processing; isolate optional external dependencies. |
| Shared state and decision provenance | Persist results or state with reproducible provenance; expose explicit failure modes. |
| Deterministic policy and exact-action approvals | Expose integration or operational interfaces; apply authorization and fail-safe validation. |
| Paper broker integration and operator console | Deliver reviewable evidence, operator workflow and integration tests; do not bypass approvals. |

### Suggested repository layout

```text
multi-agent-ai-trading-platform/
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

- [ ] Inventory existing planner, audit chain and approval interfaces; define agent contracts and permission scopes.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M2 — Core implementation

- [ ] Add research and portfolio proposal agents using read-only tools and evidence.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M3 — Integration and validation

- [ ] Add independent risk service, approval workflow, idempotent OMS dispatch and conflict handling.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

### M4 — Hardening and delivery

- [ ] Exercise prompt injection, stale-data, partial-fill and restart cases; deliver paper demo and operations runbook.
- [ ] Document interfaces, assumptions and design decisions introduced in this milestone.
- [ ] Add automated tests and store a reproducible demonstration or validation report.

## 5. Testing and validation

Implement unit tests for domain invariants, integration tests for adapter contracts and scenario tests for failure paths. Use fixed seeds where applicable; avoid testing only happy paths.

| Scenario | Required verification |
|---|---|
| Injected instructions in news | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Malicious tool arguments | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Approval replay | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Conflicting agents | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Stale quote | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Broker timeout | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |
| Duplicate fill | Reproduce the case with a fixture or injected fault; assert the documented correct outcome, rejection or recovery and retain evidence. |

For quantitative work, use chronological splits, point-in-time inputs, realistic costs where relevant, and report failed experiments as well as successful ones. For execution systems, test idempotency, uncertain outcomes and state recovery. Never infer live performance from a simulated test.

## 6. Acceptance criteria / definition of done

- [ ] Agents cannot directly submit orders.
- [ ] An approval binds exact order parameters and expires.
- [ ] Risk checks repeat before dispatch.
- [ ] All actions trace to source evidence and policy version.
- [ ] Duplicate messages never create duplicate orders.
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
