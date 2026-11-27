# Architecture & Component Boundaries

## 1. Design Principles

1. **Agents propose; deterministic code decides and executes.** Research and portfolio agents only hold read-only tool scopes (`get_quote`, `get_fundamentals`, `get_news`, `get_account_state`). They receive no reference to the OMS or broker and are structurally prevented from submitting or approving orders.
2. **Untrusted external data is quarantined.** External news and filings pass through `PromptInjectionGuard` before agent consumption; tainted items are tagged in `EvidenceItem`, excluded from sentiment scoring, and audited.
3. **Two-stage independent risk validation.** `IndependentRiskService` evaluates every proposal at `PRE_APPROVAL` and repeats the full validation suite at `PRE_DISPATCH` immediately before broker submission using fresh quotes and current persisted account balances.
4. **Exact-action, expiring, single-use approvals.** Approvals bind a canonical SHA-256 `exact_action_hash` over every executable parameter (`account_id`, `symbol`, `side`, `quantity`, `order_type`, `limit_price`, `time_in_force`, `currency`, `policy_version`, `proposal_id`), expire after `approval_ttl_seconds`, and transition to `CONSUMED` upon first dispatch.
5. **Idempotency & auditability by default.** Every dispatch requires an `idempotency_key`, every broker fill is deduplicated by `broker_fill_id`, and every state transition or denial is appended to a SHA-256 hash-chained `audit_log`.

## 2. System Architecture Diagram

```mermaid
flowchart TD
    UI["Operator Console & FastAPI API / CLI"] --> FACADE["TradingPlatform Facade"]
    FACADE --> ORCH["MultiAgentOrchestrator (Bounded Steps)"]
    FACADE --> APR["ExactActionApprovalService (Hash + TTL + Anti-Replay)"]
    FACADE --> OMS["IdempotentOMS (Single Broker Gateway)"]

    ORCH --> GW["BoundedToolGateway (RBAC + Budget + Arg Validation)"]
    GW --> GUARD["PromptInjectionGuard"]
    GW --> MKT["MarketDataProvider (Synthetic Fixtures)"]

    ORCH --> RES1["FundamentalResearchAgent (Read-Only)"]
    ORCH --> RES2["MomentumNewsResearchAgent (Read-Only)"]
    ORCH --> PORT["PortfolioAgentAdapter (Read-Only)"]
    RES1 --> GW
    RES2 --> GW
    PORT --> GW

    ORCH --> RISK["IndependentRiskService (Deterministic)"]
    ORCH --> POL["PolicyEngine (Final Authority)"]
    POL --> APR

    OMS --> APR
    OMS --> RISK
    OMS --> BRK["SimulatedPaperBroker (Paper Only)"]

    FACADE --> REPO["StateRepository (SQLite / PostgreSQL Schema)"]
    FACADE --> BUS["Typed EventBus"]
    BUS --> REPO
```

## 3. Proposal-to-Execution Sequence

```mermaid
sequenceDiagram
    participant Op as Human Operator
    participant Orch as MultiAgentOrchestrator
    participant Agents as Research & Portfolio Agents
    participant Risk as IndependentRiskService
    participant Policy as PolicyEngine
    participant Apr as ApprovalService
    participant OMS as IdempotentOMS
    participant Broker as PaperBroker

    Op->>Orch: run_cycle(symbol)
    Orch->>Agents: analyze / build_proposal (read-only tools)
    Agents-->>Orch: ResearchReports + PortfolioProposal (typed, evidence-linked)
    Orch->>Policy: check directional conflicts
    Orch->>Risk: evaluate(stage="PRE_APPROVAL")
    Risk-->>Orch: RiskAssessment (APPROVED / REJECTED)
    Orch->>Policy: evaluate_proposal(proposal, risk)
    Policy->>Apr: create_request(exact_action_hash, TTL)
    Apr-->>Op: ApprovalRequest (PENDING)

    Op->>Apr: decide(actor_id, expected_action_hash, approve=True)
    Apr-->>Op: ApprovalRequest (APPROVED)

    Op->>OMS: dispatch_approved_order(approval_id, idempotency_key)
    OMS->>Apr: validate_for_dispatch(exact_action_hash, TTL, unconsumed)
    OMS->>Risk: evaluate(stage="PRE_DISPATCH", fresh quotes & cash)
    Risk-->>OMS: RiskAssessment (APPROVED)
    OMS->>Apr: mark_consumed(order_id)
    OMS->>Broker: submit_order(client_order_id)
    Broker-->>OMS: BrokerOrderResponse + FillRecord
    OMS-->>Op: OrderRecord (FILLED / PARTIALLY_FILLED)
```

## 4. Component Boundary Matrix

| Component | Package Path | Allowed Side Effects | Explicit Prohibitions |
|---|---|---|---|
| Domain Contracts & Config | `src/trading_platform/domain/` | None (pure models & hashes) | No I/O, no live mode allowed |
| Storage & Event Bus | `src/trading_platform/storage/` | Persist state, events, append-only audit | No mutation/deletion of audit rows |
| Tool Gateway & Market Tools | `src/trading_platform/tools/` | Read fixtures, persist evidence & tool logs | Blocks all execution/admin tool names |
| Research & Portfolio Agents | `src/trading_platform/agents/` | Call read-only tools via `BoundedToolGateway` | No broker/OMS reference; cannot approve/execute |
| Independent Risk Service | `src/trading_platform/agents/risk_agent.py` | Pure deterministic limit & staleness checks | No agent influence; no order submission |
| Policy & Approval Services | `src/trading_platform/policy/` | Persist approval state & audit decisions | Rejects agent/auditor/admin approvers and `LIVE` mode |
| OMS & Paper Broker | `src/trading_platform/execution/` | Persist orders/fills, update paper ledger | Rejects dispatch if mode != `PAPER` or kill switch ON |
| FastAPI / Operator Console / CLI | `src/trading_platform/api/`, `web/`, `cli.py` | Operator workflow & observability | Cannot bypass approvals or pre-dispatch risk |
