# Data Contracts — Macro Intelligence Agent

**Schema Version:** `1.0.0`

## 1. Timestamp and Numeric Semantics

- **Timestamps:** All timestamps (`published_at`, `embargo_until`, `ingested_at`, `as_of_utc`) MUST be valid ISO-8601 strings with explicit timezone offsets (canonical output uses UTC `Z`, e.g., `2025-05-13T12:30:00Z`). Naive timestamps without timezone offsets raise `SchemaValidationError`.
- **Publication gate timestamp:** For each release, `available_at = max(published_at, embargo_until)` when `embargo_until` is provided, else `published_at`. Visibility requires `available_at <= as_of_utc`.
- **Numbers:** Parsed and calculated using exact `Decimal`. Booleans, `NaN`, and `±Inf` raise `SchemaValidationError`. Default comparison tolerance is `0.0001` (`config.numeric_tolerance`).

## 2. Canonical Units and Compatibility Matrix

Supported `Unit` enum values (`src/macro_intelligence_agent/models.py`):

| Canonical Value | Accepted Aliases | Convertible With |
|---|---|---|
| `percent_yoy` | `% YoY`, `pct_yoy`, `yoy_pct` | None (periodicity-locked) |
| `percent_mom` | `% MoM`, `pct_mom`, `mom_pct` | None (periodicity-locked) |
| `percent_qoq_saar` | `% QoQ SAAR`, `pct_qoq_saar` | None (periodicity-locked) |
| `percent_rate` | `%`, `pct`, `percent` | `bps` (`1% = 100 bps`) |
| `bps` | `basis_points` | `percent_rate` (`100 bps = 1%`) |
| `thousands` | `k` | `millions` (`1000k = 1M`) |
| `millions` | `m` | `thousands` (`1M = 1000k`) |
| `index_points` | `index` | None |

Any comparison across non-convertible units (e.g., `percent_mom` vs `percent_yoy`) raises `UnitMismatchError` internally and surfaces a `ConflictRecord(conflict_type="unit_mismatch")` plus an `AbstentionRecord(reason_code="UNIT_MISMATCH")`.

## 3. Input Schemas

### 3.1 `MacroRelease`

| Field | Type | Required | Constraints |
|---|---|---|---|
| `release_id` | `str` | Yes | Non-empty stable release identifier |
| `vintage_id` | `str` | Yes | Non-empty vintage identifier (composite primary key with `release_id`) |
| `vintage_sequence` | `int` | Yes | Integer `>= 1` ordering revisions within a `release_id` |
| `series_group` | `str` | Yes | Logical domain grouping (e.g. `US_INFLATION_POLICY`) |
| `reference_period` | `str` | Yes | Reference period label (e.g. `2025-03`) |
| `document_type` | `DocumentType` | Yes | One of `economic_release`, `central_bank_statement`, `central_bank_minutes`, `consensus_survey`, `press_report` |
| `source_id`, `source_name`, `title` | `str` | Yes | Non-empty provenance metadata |
| `published_at` | UTC ISO-8601 | Yes | Timezone-aware |
| `embargo_until` | UTC ISO-8601 | No | Optional embargo gate timestamp |
| `ingested_at` | UTC ISO-8601 | No | Optional ingestion timestamp |
| `raw_text` | `str` | Yes | Non-empty untrusted source text; hashed via SHA-256 |
| `reported_metrics` | `list[MetricObservation]` | No | Optional structured claims; each must ground in non-quarantined `raw_text` |

### 3.2 `ConsensusEstimate`

| Field | Type | Required | Constraints |
|---|---|---|---|
| `consensus_id` | `str` | Yes | Unique benchmark ID |
| `series_id` | `str` | Yes | Canonical macro series ID |
| `reference_period` | `str` | Yes | Period matching release metric |
| `expected_value` | `Decimal` | Yes | Finite number |
| `unit` | `Unit` | Yes | Canonical unit |
| `published_at` | UTC ISO-8601 | Yes | Must be `<= release.available_at` to count as pre-release consensus |
| `source_id` | `str` | Yes | Benchmark provider ID |
| `contributor_count` | `int` | No | `>= 1` if present |

## 4. Output Envelope (`AgentRunResult`)

- `metadata` (`RunMetadata`): `run_id`, `schema_version`, `config_version`, `config_sha256`, `input_sha256`, `seed`, `as_of_utc`, `python_version`, `model_provider`, `model_calls_used`.
- `brief` (`ScenarioBrief`): `brief_id`, `as_of_utc`, `series_group`, `executive_summary`, `figures`, `surprises`, `revisions`, `policy_signals`, `conflicts`, `abstentions`, `security_findings`, `scenarios`, `citations_index`, `verification_passed`, `limitations_notice`.
- `diagnostics` (`RunDiagnostics`): deterministic `counters` dict and ordered `events` tuple.

## 5. Error Codes

| Exception | Error Code | Trigger |
|---|---|---|
| `ConfigurationError` | `CONFIGURATION_ERROR` | Missing/malformed config, invalid mode, `allow_live_network=true`, disabled citation/hypothesis policy |
| `SchemaValidationError` | `SCHEMA_VALIDATION_ERROR` | Naive timestamp, non-finite/bool decimal, empty required fields, missing release key |
| `UnsupportedInputError` | `UNSUPPORTED_INPUT` | Unknown unit or unsupported `document_type` |
| `EmbargoViolationError` | `EMBARGO_VIOLATION` | Direct lookup of an embargoed/future release via `get_release_checked` |
| `UnitMismatchError` | `UNIT_MISMATCH` | Direct incompatible unit conversion attempt |
| `UntrustedInstructionError` | `UNTRUSTED_SOURCE_INSTRUCTION` | Prompt injection detected while `strict_untrusted_instruction_mode="reject"` |
| `CitationVerificationError` | `CITATION_VERIFICATION_FAILED` | Ungrounded metric, quote/offset mismatch, hash mismatch, future citation, or forbidden phrase |
| `BudgetExceededError` | `BUDGET_EXCEEDED` | Summarizer adapter exceeds `max_calls_per_run` |

## 6. Fixture Coverage

- **Valid & revision/embargo reference:** `data/fixtures/reference_cpi_release.json` + hand-calculated oracle `data/fixtures/reference_expected_oracle.json`
- **Unit mismatch & conflicting reports:** `data/fixtures/integration_unit_mismatch_and_conflict.json`
- **Security boundary (untrusted source instructions):** `data/fixtures/security_untrusted_instructions.json`
- **Curated evaluation benchmark:** `data/fixtures/gold_set.json`
- **Invalid/boundary error inputs:** Tested directly in `tests/test_domain_and_embargo.py` and `tests/test_security_repro_and_ops.py`.
