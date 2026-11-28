# Incident Investigation Report: INC-AMB-004

- **Report ID:** `RPT-INC-AMB-004-f646f3f2659d`
- **Title:** Elevated order latency with competing venue-throttling and OMS-GC-pause signals
- **Verdict:** `AMBIGUOUS`
- **Top Confidence:** `0.5377`
- **Read-Only Enforced:** `True` (Operational changes applied: `0`)
- **Input Digest:** `4f6748a476787a6a` | **Config Digest:** `a176d0b1040065a5`

## Executive Summary

Read-only investigation of INC-AMB-004 concluded with verdict AMBIGUOUS. Primary root cause assessment: NONE (ambiguous or insufficient evidence). No operational changes were executed automatically; any simulated remediation requires explicit operator approval.

## Root-Cause Hypotheses

### HYP-01-internal_oms_gc_pause: OMS JVM Garbage Collection Pause
- **Failure Mode:** `internal_oms_gc_pause` | **Service:** `oms-core` | **Confidence:** `0.5377` | **Modalities:** `alert, log, oms_event, otel_span`
- **Supporting Evidence:**
  - `EV-0001-sp-amb-001` (`otel_span`, weight=0.26): RouteOrder [ERROR] (620.0ms): stop-the-world GC pause delayed order dispatch by 590ms — _Error span on 'oms-core' matches symptom 'GC pause'_
  - `EV-0002-lg-amb-001` (`log`, weight=0.18): JVM GC pause exceeded 550ms during order routing batch — _Log entry on 'oms-core' mentions symptom 'GC pause'_
  - `EV-0007-oms-amb-001` (`oms_event`, weight=0.30): ORDER_TIMEOUT (SIMD@SIMY): Order delayed beyond budget during oms-core GC pause [reject_code=OMS_GC_STALL] — _OMS reject_code 'OMS_GC_STALL' directly matches RB-OMS-GC-006_
  - `EV-0009-al-amb-001` (`alert`, weight=0.32): [ALERT_OMS_GC_PAUSE] OMS GC Pause Spike: Single GC pause exceeded 500ms on oms-core instance 2 (gc_pause_ms=590.0 ms) — _Alert rule 'ALERT_OMS_GC_PAUSE' directly maps to RB-OMS-GC-006_
- **Counterevidence:**
  - `EV-0005-sp-amb-003` (`otel_span`, penalty=0.22): RouteOrder [OK] (8.0ms) — _Healthy OK span observed on hypothesized service 'oms-core' during incident window._
- **Uncertainty Factors:**
  - 1 counterevidence record(s) conflict with or weaken this hypothesis.
- **Recommended Diagnostic Checks:**
  - Correlate GC safepoint timestamps across all oms-core replicas
  - Verify whether non-SIMY venues experienced identical latency spikes

### HYP-02-exchange_venue_throttling: Exchange Venue Throttling
- **Failure Mode:** `exchange_venue_throttling` | **Service:** `venue-adapter` | **Confidence:** `0.5377` | **Modalities:** `alert, log, oms_event, otel_span`
- **Supporting Evidence:**
  - `EV-0003-sp-amb-002` (`otel_span`, weight=0.26): SendVenueOrder [ERROR] (615.0ms): exchange venue throttle backoff returned HTTP 429 / VENUE_THROTTLE — _Error span on 'venue-adapter' matches symptom 'venue throttle'_
  - `EV-0004-lg-amb-002` (`log`, weight=0.18): Venue SIMY responded with VENUE_THROTTLE rate backoff — _Log entry on 'venue-adapter' mentions symptom 'VENUE_THROTTLE'_
  - `EV-0008-oms-amb-002` (`oms_event`, weight=0.30): THROTTLE_TRIGGERED (SIMD@SIMY): Order throttled by external venue adapter SIMY [reject_code=VENUE_THROTTLE] — _OMS reject_code 'VENUE_THROTTLE' directly matches RB-VENUE-THROTTLE-007_
  - `EV-0010-al-amb-002` (`alert`, weight=0.32): [ALERT_VENUE_THROTTLE] Exchange Venue Throttle Backoff: Venue SIMY returned throttle backoff responses (venue_throttle_count=12.0 count) — _Alert rule 'ALERT_VENUE_THROTTLE' directly maps to RB-VENUE-THROTTLE-007_
- **Counterevidence:**
  - `EV-0006-sp-amb-004` (`otel_span`, penalty=0.22): SendVenueOrder [OK] (9.5ms) — _Healthy OK span observed on hypothesized service 'venue-adapter' during incident window._
- **Uncertainty Factors:**
  - 1 counterevidence record(s) conflict with or weaken this hypothesis.
- **Recommended Diagnostic Checks:**
  - Inspect SIMY venue status feed and per-venue throttle counters
  - Compare latency across SIMX vs SIMY adapters

## Surfaced Uncertainty & Caveats

- Ambiguous root cause: 'internal_oms_gc_pause' (0.54) and 'exchange_venue_throttling' (0.54) are within ambiguity margin 0.12 (delta=0.0000).
- Run discriminating diagnostic checks before approving any targeted remediation.

## Normalized Incident Timeline (UTC)

| Evidence ID | Timestamp (UTC) | Source | Service | Severity | Anomalous | Summary |
|---|---|---|---|---|---|---|
| `EV-0001-sp-amb-001` | `2026-04-18T15:20:01+00:00` | `otel_span` | `oms-core` | `ERROR` | `True` | RouteOrder [ERROR] (620.0ms): stop-the-world GC pause delayed order dispatch by 590ms |
| `EV-0002-lg-amb-001` | `2026-04-18T15:20:01.010000+00:00` | `log` | `oms-core` | `ERROR` | `True` | JVM GC pause exceeded 550ms during order routing batch |
| `EV-0003-sp-amb-002` | `2026-04-18T15:20:01.050000+00:00` | `otel_span` | `venue-adapter` | `ERROR` | `True` | SendVenueOrder [ERROR] (615.0ms): exchange venue throttle backoff returned HTTP 429 / VENUE_THROTTLE |
| `EV-0004-lg-amb-002` | `2026-04-18T15:20:01.060000+00:00` | `log` | `venue-adapter` | `ERROR` | `True` | Venue SIMY responded with VENUE_THROTTLE rate backoff |
| `EV-0005-sp-amb-003` | `2026-04-18T15:20:01.200000+00:00` | `otel_span` | `oms-core` | `INFO` | `False` | RouteOrder [OK] (8.0ms) |
| `EV-0006-sp-amb-004` | `2026-04-18T15:20:01.250000+00:00` | `otel_span` | `venue-adapter` | `INFO` | `False` | SendVenueOrder [OK] (9.5ms) |
| `EV-0007-oms-amb-001` | `2026-04-18T15:20:01.620000+00:00` | `oms_event` | `oms-core` | `ERROR` | `True` | ORDER_TIMEOUT (SIMD@SIMY): Order delayed beyond budget during oms-core GC pause [reject_code=OMS_GC_STALL] |
| `EV-0008-oms-amb-002` | `2026-04-18T15:20:01.665000+00:00` | `oms_event` | `venue-adapter` | `ERROR` | `True` | THROTTLE_TRIGGERED (SIMD@SIMY): Order throttled by external venue adapter SIMY [reject_code=VENUE_THROTTLE] |
| `EV-0009-al-amb-001` | `2026-04-18T15:20:03+00:00` | `alert` | `oms-core` | `ERROR` | `True` | [ALERT_OMS_GC_PAUSE] OMS GC Pause Spike: Single GC pause exceeded 500ms on oms-core instance 2 (gc_pause_ms=590.0 ms) |
| `EV-0010-al-amb-002` | `2026-04-18T15:20:03.050000+00:00` | `alert` | `venue-adapter` | `ERROR` | `True` | [ALERT_VENUE_THROTTLE] Exchange Venue Throttle Backoff: Venue SIMY returned throttle backoff responses (venue_throttle_count=12.0 count) |

## Proposed Simulated Remediations (Explicit Approval Required)

- `REM-INC-AMB-004-01`: action=`shift_traffic_to_standby_oms_sim`, target=`oms-core`, risk=`HIGH`, plan_digest=`0f14792b03ed1c49...`, auto_executed=`False`
  - **Gate:** Root cause verdict is AMBIGUOUS; run discriminating checks or explicitly set acknowledge_ambiguity=True in OperatorApproval.
- `REM-INC-AMB-004-02`: action=`enable_venue_pacing_backoff_sim`, target=`venue-adapter`, risk=`LOW`, plan_digest=`e7924a46474ee1cc...`, auto_executed=`False`
  - **Gate:** Root cause verdict is AMBIGUOUS; run discriminating checks or explicitly set acknowledge_ambiguity=True in OperatorApproval.
