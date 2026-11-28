# Incident Investigation Report: INC-REF-001

- **Report ID:** `RPT-INC-REF-001-2f00c87cc6a7`
- **Title:** Order-routing gateway connection pool exhaustion causing ACK timeouts
- **Verdict:** `DETERMINED`
- **Top Confidence:** `0.8965`
- **Read-Only Enforced:** `True` (Operational changes applied: `0`)
- **Input Digest:** `951aa27f87d19820` | **Config Digest:** `a176d0b1040065a5`

## Executive Summary

Read-only investigation of INC-REF-001 concluded with verdict DETERMINED. Primary root cause assessment: gateway_connection_pool_exhaustion (service=fix-gateway, confidence=0.90, runbook=RB-FIX-POOL-001). No operational changes were executed automatically; any simulated remediation requires explicit operator approval.

## Root-Cause Hypotheses

### HYP-01-gateway_connection_pool_exhaustion (PRIMARY): FIX Gateway Connection Pool Exhaustion
- **Failure Mode:** `gateway_connection_pool_exhaustion` | **Service:** `fix-gateway` | **Confidence:** `0.8965` | **Modalities:** `alert, log, oms_event, otel_span`
- **Supporting Evidence:**
  - `EV-0004-lg-ref-001` (`log`, weight=0.18): FIX socket pool utilization reached 100% (64/64 active connections); queueing order ORD-SIM-9001 — _Log entry on 'fix-gateway' mentions symptom 'socket pool utilization'_
  - `EV-0005-sp-ref-003` (`otel_span`, weight=0.26): AcquirePoolConnection [ERROR] (2410.0ms): connection pool exhausted: 64/64 active sockets waiting — _Error span on 'fix-gateway' matches symptom 'connection pool exhausted'_
  - `EV-0006-lg-ref-002` (`log`, weight=0.18): AcquirePoolConnection timed out after 2410ms due to connection pool exhaustion on simx_fix_pool — _Log entry on 'fix-gateway' mentions symptom 'AcquirePoolConnection'_
  - `EV-0007-oms-ref-002` (`oms_event`, weight=0.30): ORDER_TIMEOUT (SIMA@SIMX): Order ACK timeout because fix-gateway connection pool exhausted [reject_code=GW_POOL_EXHAUSTED] — _OMS reject_code 'GW_POOL_EXHAUSTED' directly matches RB-FIX-POOL-001_
  - `EV-0009-sp-ref-004` (`otel_span`, weight=0.26): AcquirePoolConnection [ERROR] (2505.0ms): connection pool exhausted: 64/64 active sockets — _Error span on 'fix-gateway' matches symptom 'connection pool exhausted'_
  - `EV-0010-al-ref-001` (`alert`, weight=0.32): [ALERT_GW_POOL_EXHAUSTION] FIX Gateway Connection Pool Saturated: fix-gateway active socket pool reached 100% capacity with elevated order ACK timeouts (gateway_pool_utilization_pct=100.0 percent) — _Alert rule 'ALERT_GW_POOL_EXHAUSTION' directly maps to RB-FIX-POOL-001_
  - `EV-0011-oms-ref-003` (`oms_event`, weight=0.30): ORDER_TIMEOUT (SIMA@SIMX): Order ACK timeout on fix-gateway due to exhausted socket pool [reject_code=GW_POOL_EXHAUSTED] — _OMS reject_code 'GW_POOL_EXHAUSTED' directly matches RB-FIX-POOL-001_
- **Recommended Diagnostic Checks:**
  - Verify fix-gateway pool.active vs pool.max telemetry
  - Confirm risk-engine spans remain healthy to rule out upstream bottleneck

## Normalized Incident Timeline (UTC)

| Evidence ID | Timestamp (UTC) | Source | Service | Severity | Anomalous | Summary |
|---|---|---|---|---|---|---|
| `EV-0001-sp-ref-001` | `2026-04-15T14:30:01+00:00` | `otel_span` | `order-router` | `ERROR` | `True` | SubmitOrder [ERROR] (2450.0ms): downstream gateway timeout after 2400ms |
| `EV-0002-oms-ref-001` | `2026-04-15T14:30:01.002000+00:00` | `oms_event` | `oms-core` | `INFO` | `False` | ORDER_NEW (SIMA@SIMX): Accepted simulated order ORD-SIM-9001 for routing to fix-gateway |
| `EV-0003-sp-ref-002` | `2026-04-15T14:30:01.015000+00:00` | `otel_span` | `risk-engine` | `INFO` | `False` | PreTradeRiskCheck [OK] (12.4ms) |
| `EV-0004-lg-ref-001` | `2026-04-15T14:30:01.028000+00:00` | `log` | `fix-gateway` | `WARNING` | `True` | FIX socket pool utilization reached 100% (64/64 active connections); queueing order ORD-SIM-9001 |
| `EV-0005-sp-ref-003` | `2026-04-15T14:30:01.030000+00:00` | `otel_span` | `fix-gateway` | `ERROR` | `True` | AcquirePoolConnection [ERROR] (2410.0ms): connection pool exhausted: 64/64 active sockets waiting |
| `EV-0006-lg-ref-002` | `2026-04-15T14:30:03.440000+00:00` | `log` | `fix-gateway` | `ERROR` | `True` | AcquirePoolConnection timed out after 2410ms due to connection pool exhaustion on simx_fix_pool |
| `EV-0007-oms-ref-002` | `2026-04-15T14:30:03.455000+00:00` | `oms_event` | `fix-gateway` | `ERROR` | `True` | ORDER_TIMEOUT (SIMA@SIMX): Order ACK timeout because fix-gateway connection pool exhausted [reject_code=GW_POOL_EXHAUSTED] |
| `EV-0008-lg-ref-003` | `2026-04-15T14:30:04+00:00` | `log` | `risk-engine` | `INFO` | `False` | PreTradeRiskCheck health heartbeat nominal; p99 latency 14ms |
| `EV-0009-sp-ref-004` | `2026-04-15T14:30:04.200000+00:00` | `otel_span` | `fix-gateway` | `ERROR` | `True` | AcquirePoolConnection [ERROR] (2505.0ms): connection pool exhausted: 64/64 active sockets |
| `EV-0010-al-ref-001` | `2026-04-15T14:30:05+00:00` | `alert` | `fix-gateway` | `CRITICAL` | `True` | [ALERT_GW_POOL_EXHAUSTION] FIX Gateway Connection Pool Saturated: fix-gateway active socket pool reached 100% capacity with elevated order ACK timeouts (gateway_pool_utilization_pct=100.0 percent) |
| `EV-0011-oms-ref-003` | `2026-04-15T14:30:06.710000+00:00` | `oms_event` | `fix-gateway` | `ERROR` | `True` | ORDER_TIMEOUT (SIMA@SIMX): Order ACK timeout on fix-gateway due to exhausted socket pool [reject_code=GW_POOL_EXHAUSTED] |

## Proposed Simulated Remediations (Explicit Approval Required)

- `REM-INC-REF-001-01`: action=`drain_and_recycle_gateway_pool`, target=`fix-gateway`, risk=`MEDIUM`, plan_digest=`ac163e42ad1912bd...`, auto_executed=`False`
