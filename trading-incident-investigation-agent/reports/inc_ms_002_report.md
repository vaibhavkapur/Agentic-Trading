# Incident Investigation Report: INC-MS-002

- **Report ID:** `RPT-INC-MS-002-84e88f1c0151`
- **Title:** OMS rate-limit throttle spike with missing intermediate spans and misleading market-data logs
- **Verdict:** `DETERMINED`
- **Top Confidence:** `0.7783`
- **Read-Only Enforced:** `True` (Operational changes applied: `0`)
- **Input Digest:** `117e0def6f94e720` | **Config Digest:** `a176d0b1040065a5`

## Executive Summary

Read-only investigation of INC-MS-002 concluded with verdict DETERMINED. Primary root cause assessment: oms_rate_limit_throttle (service=oms-core, confidence=0.78, runbook=RB-OMS-THROTTLE-004). No operational changes were executed automatically; any simulated remediation requires explicit operator approval.

## Root-Cause Hypotheses

### HYP-01-oms_rate_limit_throttle (PRIMARY): OMS Order Rate-Limit Throttle Exhaustion
- **Failure Mode:** `oms_rate_limit_throttle` | **Service:** `oms-core` | **Confidence:** `0.7783` | **Modalities:** `alert, log, oms_event, otel_span`
- **Supporting Evidence:**
  - `EV-0001-sp-ms-001` (`otel_span`, weight=0.20): SubmitOrder [ERROR] (145.0ms): OMS returned rate limit throttle rejection — _Upstream error span on 'order-router' reports 'rate limit'_
  - `EV-0002-sp-ms-003` (`otel_span`, weight=0.26): EnforceOrderRateLimit [ERROR] (98.0ms): token bucket exhausted: order rate limit exceeded (500/500 req/s) — _Error span on 'oms-core' matches symptom 'token bucket exhausted'_
  - `EV-0003-lg-ms-001` (`log`, weight=0.18): OMS token bucket simx_burst_bucket depleted; throttling ORD-SIM-2101 with OMS_RATE_LIMIT — _Log entry on 'oms-core' mentions symptom 'throttling'_
  - `EV-0004-oms-ms-001` (`oms_event`, weight=0.30): THROTTLE_TRIGGERED (SIMB@SIMX): Order throttled by oms-core rate limiter bucket simx_burst_bucket [reject_code=OMS_RATE_LIMIT] — _OMS reject_code 'OMS_RATE_LIMIT' directly matches RB-OMS-THROTTLE-004_
  - `EV-0006-sp-ms-004` (`otel_span`, weight=0.26): EnforceOrderRateLimit [ERROR] (102.0ms): token bucket exhausted: throttle reject OMS_RATE_LIMIT — _Error span on 'oms-core' matches symptom 'token bucket exhausted'_
  - `EV-0007-oms-ms-002` (`oms_event`, weight=0.30): ORDER_REJECT (SIMB@SIMX): Order rejected due to oms-core order rate limit exhaustion [reject_code=OMS_RATE_LIMIT] — _OMS reject_code 'OMS_RATE_LIMIT' directly matches RB-OMS-THROTTLE-004_
  - `EV-0008-al-ms-001` (`alert`, weight=0.32): [ALERT_OMS_THROTTLE_SPIKE] OMS Order Rate-Limit Throttle Spike: oms-core throttle rejection rate exceeded threshold on simx_burst_bucket (oms_throttle_reject_rate_pct=18.4 percent) — _Alert rule 'ALERT_OMS_THROTTLE_SPIKE' directly maps to RB-OMS-THROTTLE-004_
- **Uncertainty Factors:**
  - 2 distributed trace gap(s) detected; intermediate span visibility is incomplete.
- **Recommended Diagnostic Checks:**
  - Check oms-core token bucket utilization and burst config
  - Verify whether missing intermediate spans conceal upstream burst retry loop

### HYP-02-market_data_feed_stale: Market Data Feed Stale Quotes
- **Failure Mode:** `market_data_feed_stale` | **Service:** `market-data-feed` | **Confidence:** `0.0000` | **Modalities:** `log`
- **Supporting Evidence:**
  - `EV-0009-lg-ms-redherring-01` (`log`, weight=0.06): Transient backup feed disconnect on archival replay channel; stale quote cache warning ignored on live book — _Log entry on 'market-data-feed' mentions symptom 'feed disconnect'_
  - `EV-0010-lg-ms-redherring-02` (`log`, weight=0.06): Secondary md gap noticed during background snapshot checksum; primary quote feed unaffected — _Log entry on 'market-data-feed' mentions symptom 'md gap'_
- **Counterevidence:**
  - `EV-0005-sp-ms-005` (`otel_span`, penalty=0.22): PublishTopOfBook [OK] (3.2ms) — _Healthy OK span observed on hypothesized service 'market-data-feed' during incident window._
  - `EV-0009-lg-ms-redherring-01` (`log`, penalty=0.14): Transient backup feed disconnect on archival replay channel; stale quote cache warning ignored on live book — _Log indicates archival/secondary channel or unaffected primary feed; treated as potential red herring._
  - `EV-0010-lg-ms-redherring-02` (`log`, penalty=0.14): Secondary md gap noticed during background snapshot checksum; primary quote feed unaffected — _Log indicates archival/secondary channel or unaffected primary feed; treated as potential red herring._
- **Uncertainty Factors:**
  - Earliest supporting evidence lags incident onset by 4400ms with no trace_id or order_id correlation.
  - Supported by log entries only (no corroborating OpenTelemetry spans, OMS events, or alerts).
  - 2 distributed trace gap(s) detected; intermediate span visibility is incomplete.
  - 3 counterevidence record(s) conflict with or weaken this hypothesis.
- **Recommended Diagnostic Checks:**
  - Confirm PublishTopOfBook spans show elevated quote age or errors
  - Confirm STALE_PRICE_REJECT events in OMS

## Surfaced Uncertainty & Caveats

- Incomplete trace graph: 2 trace gap(s) detected (missing parent span or clock skew).

## Distributed Trace Gaps

- `missing_parent_span` in trace `tr-ms-200`: Span 'sp-ms-003' (oms-core.EnforceOrderRateLimit) references missing parent_span_id 'sp-ms-002-MISSING' in trace 'tr-ms-200'.
- `missing_parent_span` in trace `tr-ms-201`: Span 'sp-ms-004' (oms-core.EnforceOrderRateLimit) references missing parent_span_id 'sp-ms-002-MISSING-B' in trace 'tr-ms-201'.

## Normalized Incident Timeline (UTC)

| Evidence ID | Timestamp (UTC) | Source | Service | Severity | Anomalous | Summary |
|---|---|---|---|---|---|---|
| `EV-0001-sp-ms-001` | `2026-04-16T09:15:00.100000+00:00` | `otel_span` | `order-router` | `ERROR` | `True` | SubmitOrder [ERROR] (145.0ms): OMS returned rate limit throttle rejection |
| `EV-0002-sp-ms-003` | `2026-04-16T09:15:00.140000+00:00` | `otel_span` | `oms-core` | `ERROR` | `True` | EnforceOrderRateLimit [ERROR] (98.0ms): token bucket exhausted: order rate limit exceeded (500/500 req/s) |
| `EV-0003-lg-ms-001` | `2026-04-16T09:15:00.150000+00:00` | `log` | `oms-core` | `ERROR` | `True` | OMS token bucket simx_burst_bucket depleted; throttling ORD-SIM-2101 with OMS_RATE_LIMIT |
| `EV-0004-oms-ms-001` | `2026-04-16T09:15:00.160000+00:00` | `oms_event` | `oms-core` | `ERROR` | `True` | THROTTLE_TRIGGERED (SIMB@SIMX): Order throttled by oms-core rate limiter bucket simx_burst_bucket [reject_code=OMS_RATE_LIMIT] |
| `EV-0005-sp-ms-005` | `2026-04-16T09:15:00.200000+00:00` | `otel_span` | `market-data-feed` | `INFO` | `False` | PublishTopOfBook [OK] (3.2ms) |
| `EV-0006-sp-ms-004` | `2026-04-16T09:15:01.050000+00:00` | `otel_span` | `oms-core` | `ERROR` | `True` | EnforceOrderRateLimit [ERROR] (102.0ms): token bucket exhausted: throttle reject OMS_RATE_LIMIT |
| `EV-0007-oms-ms-002` | `2026-04-16T09:15:01.160000+00:00` | `oms_event` | `oms-core` | `ERROR` | `True` | ORDER_REJECT (SIMB@SIMX): Order rejected due to oms-core order rate limit exhaustion [reject_code=OMS_RATE_LIMIT] |
| `EV-0008-al-ms-001` | `2026-04-16T09:15:02+00:00` | `alert` | `oms-core` | `CRITICAL` | `True` | [ALERT_OMS_THROTTLE_SPIKE] OMS Order Rate-Limit Throttle Spike: oms-core throttle rejection rate exceeded threshold on simx_burst_bucket (oms_throttle_reject_rate_pct=18.4 percent) |
| `EV-0009-lg-ms-redherring-01` | `2026-04-16T09:15:04.500000+00:00` | `log` | `market-data-feed` | `ERROR` | `True` | Transient backup feed disconnect on archival replay channel; stale quote cache warning ignored on live book |
| `EV-0010-lg-ms-redherring-02` | `2026-04-16T09:15:05+00:00` | `log` | `market-data-feed` | `WARNING` | `True` | Secondary md gap noticed during background snapshot checksum; primary quote feed unaffected |

## Proposed Simulated Remediations (Explicit Approval Required)

- `REM-INC-MS-002-01`: action=`rebalance_oms_throttle_bucket_sim`, target=`oms-core`, risk=`MEDIUM`, plan_digest=`9d38fe37afb3cd5a...`, auto_executed=`False`
