# Trading Incident Investigation Agent

An offline, deterministic prototype that reconstructs simulated trading incidents from synthetic OpenTelemetry traces, structured logs, OMS events, alerts, and runbooks — producing cited root-cause reports with calibrated confidence, counterevidence, prompt-injection containment, and approval-gated simulated remediation.

> **Scope & Safety Notice:** Independently developed educational/research prototype operating strictly on synthetic, paper, or simulated telemetry (`environment in {"synthetic", "paper", "sim"}`). Read-only analysis is enforced by default (`operational_changes_applied = 0`). Live capital, real customer logs, and production credentials are excluded.

## Core Capabilities

1. **Deterministic Timeline Normalization & Trace Gap Analysis (`timeline.py`):** Normalizes heterogeneous telemetry into exact integer UTC nanoseconds with deterministic tie-breaking, correlation grouping, and OpenTelemetry `missing_parent_span` / `clock_skew` detection.
2. **Untrusted-Data Sanitization (`security.py`):** Redacts secrets (Bearer tokens, API keys, passwords, AWS-style keys) and quarantines indirect prompt-injection directives embedded in logs or span attributes before downstream processing or optional LLM summarization.
3. **Runbook Retrieval & Multi-Modality Hypothesis Testing (`runbooks.py`, `hypotheses.py`):** Matches runbooks deterministically and evaluates candidate hypotheses across independent modalities (`alert`, `oms_event`, `otel_span`, `log`), down-weighting uncorroborated log-only red herrings, extracting counterevidence, penalizing missing trace visibility, and flagging `AMBIGUOUS` root causes explicitly.
4. **Approval-Gated Simulated Remediation & Recovery Verification (`remediation.py`):** Generates SHA-256 `plan_digest`-bound proposals from a strict allowlist (blocking forbidden actions unconditionally), validates explicit operator approval (role, digest, expiry, ambiguity acknowledgement), simulates remediation with a fixed seed, and verifies post-remediation recovery metrics.

## Repository Layout

```text
trading-incident-investigation-agent/
├── config/default.json               # Versioned thresholds, approver roles, budgets, seed
├── data/fixtures/                    # Synthetic valid, edge-case, security, ambiguous & invalid fixtures + oracle
├── docs/
│   ├── architecture.md               # Mermaid component diagram, data flow, invariants, trade-offs
│   ├── contracts.md                  # Pydantic v2 input/output schemas, units, errors
│   ├── integration.md                # Adapter boundaries, licenses, fixture provenance
│   ├── runbook.md                    # Setup, demo, validation, diagnostics & recovery
│   └── adr/0001-deterministic-policy-and-untrusted-telemetry.md
├── reports/                          # Acceptance report + versioned raw JSON/Markdown outputs
├── scripts/run_evaluation.py         # Reproducible benchmark & report generator
├── src/trading_incident_agent/       # Typed Python package (Pydantic v2 + stdlib)
├── tests/                            # 16 unit, integration, security, and boundary tests
├── pyproject.toml
├── plan.md
└── README.md
```

## Quickstart

### 1. Setup

```bash
cd trading-incident-investigation-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Run Read-Only Demo (No Operational Changes)

```bash
trading-incident-agent demo \
  --fixture data/fixtures/inc_ref_001_gateway_pool.json \
  --config config/default.json
```

Add `--approve-demo` to simulate explicit `oncall_sre` approval bound to `plan_digest` and run seeded recovery verification:

```bash
trading-incident-agent demo \
  --fixture data/fixtures/inc_ref_001_gateway_pool.json \
  --config config/default.json \
  --approve-demo
```

### 3. Run Tests & Reproducible Evaluation

```bash
pytest -v
python scripts/run_evaluation.py
```

*(Without editable install, prefix commands with `PYTHONPATH=src` and invoke `python -m trading_incident_agent.cli ...`.)*

## Example Output (Abbreviated)

From `INC-REF-001` (`reports/inc_ref_001_report.md` and `reports/remediation_demo_receipt.json`):

```markdown
# Incident Investigation Report: INC-REF-001
- Report ID: `RPT-INC-REF-001-2f00c87cc6a7`
- Verdict: `DETERMINED` | Top Confidence: `0.8965`
- Read-Only Enforced: `True` (Operational changes applied: `0`)
- Primary Root Cause: `gateway_connection_pool_exhaustion` (`fix-gateway`, `RB-FIX-POOL-001`)
  - Supporting Modalities: `alert, log, oms_event, otel_span` (7 cited evidence records)
- Proposed Remediation: `REM-INC-REF-001-01` (`drain_and_recycle_gateway_pool`, `auto_executed=False`)
```

After explicit operator approval (`APR-REF-001-DEMO`):
- `status`: `EXECUTED_RECOVERED` (`seed=42`)
- `gateway_pool_utilization_pct`: `100.0%` → `39.285%` (`< 75.0%`)
- `p99_ack_latency_ms`: `2450.0ms` → `46.313ms` (`< 150.0ms`)
- `order_timeout_rate_pct`: `14.2%` → `0.198%` (`< 0.5%`)

## Measured Results (Synthetic Fixture Benchmark)

Measured locally on Python `3.12.15`, `pydantic 2.14.4`, `pytest 8.4.2`, `config/default.json`, `seed=42`. **Note:** All values are actual observations on the 4 synthetic fixtures in `data/fixtures/`, not production benchmarks.

| Metric | Observed Value (Synthetic Fixtures) | Evidence Artifact |
|---|---|---|
| Automated test suite (`pytest -v`) | **16 / 16 passed** (`0.05s`) | `tests/` |
| Mean timeline ordering accuracy (exact / pairwise) | **1.0000 / 1.0000** | `reports/evaluation_summary.json` |
| Mean cited evidence precision / recall | **1.0000 / 1.0000** | `reports/evaluation_summary.json` |
| Prompt-injection payloads quarantined (`INC-PI-003`) | **3 / 3** (plus **2 / 2** synthetic secrets redacted) | `reports/inc_pi_003_report.json` |
| Missing parent spans detected (`INC-MS-002`) | **2 / 2** (red-herring logs rejected) | `reports/inc_ms_002_report.json` |
| Ambiguous root cause surfaced (`INC-AMB-004`) | **`AMBIGUOUS`** (`0.5377` vs `0.5377`) | `reports/inc_amb_004_report.json` |
| Automatic operational changes during investigation | **0** | `reports/evaluation_summary.json` |

Full criterion-by-criterion acceptance mapping is in [reports/acceptance.md](reports/acceptance.md).

## Documentation

- [Architecture & Component Diagram](docs/architecture.md)
- [ADR-0001: Deterministic Policy & Untrusted-Telemetry Boundary](docs/adr/0001-deterministic-policy-and-untrusted-telemetry.md)
- [Data Contracts & Error Taxonomy](docs/contracts.md)
- [Integration Boundaries, Licenses & Provenance](docs/integration.md)
- [Operator & Developer Runbook](docs/runbook.md)
- [Acceptance Evidence Report](reports/acceptance.md)

## Assumptions & Known Limitations

- **Synthetic telemetry only:** Inputs are pre-packaged synthetic JSON bundles; live OpenTelemetry OTLP ingestion, log aggregation pipelines, and production FIX/OMS connectors are intentionally out of scope.
- **Runbook-grounded hypothesis space:** Candidate hypotheses derive from provided runbooks; if no runbook matches anomalous telemetry, the agent returns `INSUFFICIENT_EVIDENCE` rather than speculating.
- **Offline narrative default:** By default (`advisor_mode="offline_template"`), narrative summaries are generated deterministically offline. External LLM providers can be plugged in via `CallbackNarrativeAdvisor`, but live external API calls are not tested in CI.
- **Not production-ready:** Any future production adoption requires dedicated security, operational, legal, and risk review.
