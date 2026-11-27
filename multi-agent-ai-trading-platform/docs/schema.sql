-- PostgreSQL-compatible schema for Multi-Agent AI Trading Platform (Project 02 of 25)
-- Local prototype executes equivalent DDL in SQLite via StateRepository.

CREATE TABLE IF NOT EXISTS platform_state (
    key TEXT PRIMARY KEY,
    value_json JSONB NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    started_at_utc TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    symbol TEXT,
    kind TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    tainted_injection_detected BOOLEAN NOT NULL DEFAULT FALSE,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS research_reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    agent_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stance TEXT NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    symbol TEXT NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    symbol TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    exact_action_hash CHAR(64) NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    assessment_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
    stage TEXT NOT NULL CHECK (stage IN ('PRE_APPROVAL', 'PRE_DISPATCH')),
    status TEXT NOT NULL CHECK (status IN ('APPROVED', 'REJECTED')),
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id),
    exact_action_hash CHAR(64) NOT NULL,
    status TEXT NOT NULL,
    expires_at_utc TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    client_order_id TEXT NOT NULL UNIQUE,
    approval_id TEXT NOT NULL REFERENCES approvals(approval_id),
    status TEXT NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    broker_fill_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    run_id TEXT,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    run_id TEXT,
    entity_type TEXT,
    entity_id TEXT,
    evidence_ids_json JSONB NOT NULL,
    payload_json JSONB NOT NULL,
    prev_hash CHAR(64) NOT NULL,
    entry_hash CHAR(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence_items(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_orders_approval ON orders(approval_id);
CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_log(run_id);
