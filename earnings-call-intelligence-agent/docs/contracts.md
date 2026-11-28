# Data Contracts — Earnings Call Intelligence Agent

**Input Schema Version:** `1.0.0`  
**Output Schema Version:** `1.0.0`  
**Config Schema Version:** `1.0.0`

## 1. Canonical Input Contract (`TranscriptInput`)

| Field | Type | Required | Constraints & Semantics |
|---|---|---|---|
| `schema_version` | `string` | Yes | Must be in `{"1.0.0"}`; otherwise `UNSUPPORTED_SCHEMA_VERSION` |
| `transcript_id` | `string` | Yes | Non-empty stable source identifier |
| `ticker` | `string` | Yes | Non-empty symbol, normalized uppercase |
| `company_name` | `string` | Yes | Non-empty issuer display name |
| `fiscal_period` | `string` | Yes | Normalized to canonical period (e.g. `Q4_FY2025`, `FY2026`, `CY2026`) |
| `call_timestamp` | `string` | Yes | Timezone-aware ISO-8601 timestamp (normalized to UTC `Z`) |
| `published_at` | `string` | Yes | Timezone-aware ISO-8601 timestamp; must satisfy `published_at >= call_timestamp` |
| `filing_timestamp` | `string` | Yes | Timezone-aware ISO-8601 timestamp of associated filing/release |
| `currency` | `string` | Yes | Must be in `config.supported_currencies` (default `["USD"]`) |
| `language` | `string` | Yes | Must be in `config.supported_languages` (default `["en"]`) |
| `source_name` | `string` | Yes | Provenance label (e.g. `synthetic_educational_fixture`) |
| `source_license` | `string` | Yes | License identifier (e.g. `MIT-synthetic`) |
| `segments` | `TranscriptSegment[]` | Yes | Non-empty list, length `<= config.max_segments`, unique `segment_id` |
| `prior_guidance` | `PriorGuidanceRecord[]` | No | Optional historical guidance baselines for diffing |
| `questions` | `QuestionRequest[]` | No | Optional analyst/user questions evaluated with strict abstention |

### `TranscriptSegment`
- `segment_id` (`string`, unique, non-empty)
- `speaker` (`string`, non-empty)
- `speaker_role` (`CEO | CFO | COO | IR | EXECUTIVE | ANALYST | OPERATOR | UNKNOWN`)
- `section` (`PREPARED_REMARKS | QA | OPERATOR_INTRO | UNKNOWN`)
- `text` (`string`, non-empty; treated as untrusted data)
- `start_offset_sec`, `end_offset_sec` (`number`, `0 <= start_offset_sec <= end_offset_sec`)

### `PriorGuidanceRecord`
- `guidance_id`, `metric_name`, `fiscal_period`, `accounting_basis` (`GAAP | NON_GAAP | UNSPECIFIED`)
- `point_value` or (`value_low`, `value_high`) with `value_low <= value_high`
- `unit` (raw unit string normalized via unit table below)
- `source_ref`, `published_at` (timezone-aware UTC ISO-8601)

## 2. Units & Fiscal Period Normalization

### Unit Normalization Table

| Raw Unit Inputs | Canonical Unit | Scale Factor |
|---|---|---|
| `usd_billions`, `billion`, `billions`, `bn`, `b` | `USD_MILLIONS` | `× 1000.0` |
| `usd_millions`, `million`, `millions`, `mm`, `m` | `USD_MILLIONS` | `× 1.0` |
| `usd_thousands`, `thousand`, `thousands`, `k` | `USD_MILLIONS` | `× 0.001` |
| `usd` | `USD_MILLIONS` | `× 1e-6` |
| `usd_per_share`, `per_share`, `eps` | `USD_PER_SHARE` | `× 1.0` |
| `percent`, `percentage`, `%`, `pct` | `PERCENT` | `× 1.0` |
| `bps`, `basis_points`, `basis points` | `BPS` | `× 1.0` |
| `count`, `customers` | `COUNT` | `× 1.0` |
| `ratio`, `x` | `RATIO` | `× 1.0` |

Any unrecognized unit raises `UnsupportedInputError(code="UNSUPPORTED_UNIT")`.

### Fiscal Period Conventions
- Quarterly: `Q1_FY2026` (accepts `Q1 FY2026`, `Q1 2026`, `1Q26`, `first quarter of fiscal 2026`)
- Full Fiscal Year: `FY2026` (accepts `FY2026`, `FY26`, `full-year 2026`, `fiscal year 2026`)
- Calendar Year: `CY2026` (accepts `CY2026`, `calendar year 2026`)
- Half Year: `H1_FY2026` / `H2_FY2026`

## 3. Timestamp & Freshness Semantics
- All timestamps must carry an explicit UTC `Z` or timezone offset; naive timestamps fail with `NAIVE_TIMESTAMP`.
- `age_days = (as_of_timestamp - published_at) / 86400`.
- If `as_of_timestamp` is omitted, it defaults to `published_at` to keep offline runs deterministic.
- When `age_days > config.max_source_age_days`, `source_freshness.is_stale = True`, a `STALE_SOURCE` warning is recorded, guidance comparisons receive the `"STALE_SOURCE"` flag, and QA abstains with `AbstentionReason.STALE_SOURCE` (under default `stale_policy="abstain"`).

## 4. Stable Identifiers & Output Contract (`AnalysisReport`)
- `run_id`: `run_<sha256(input_digest, config_digest, seed, as_of_timestamp)[:12]>`
- `claim_id`: `clm_<sha256(segment_id, char_start, char_end, metric, period, basis, unit, low, high)[:12]>`
- `comparison_id`: `cmp_<sha256(metric, period, basis, unit, supporting_claim_ids)[:12]>`
- `event_id`: `inj_<sha256(segment_id, pattern_name, char_start, char_end)[:12]>`
- Top-level fields: `schema_version`, `run_id`, `input_digest`, `config_digest`, `seed`, `transcript_id`, `ticker`, `company_name`, `fiscal_period`, `as_of_timestamp`, `source_freshness`, `trade_action_permitted` (always `false`), `claims`, `guidance_comparisons`, `question_answers`, `prompt_injection_events`, `warnings`, `diagnostics`, `runtime_metadata`, `structured_logs`.

## 5. Validation & Operational Error Codes

| Error Class | Code | Trigger |
|---|---|---|
| `SchemaValidationError` | `INVALID_ROOT`, `MISSING_OR_INVALID_FIELD`, `EMPTY_SEGMENTS`, `DUPLICATE_SEGMENT_ID`, `INVALID_TIMESTAMP`, `NAIVE_TIMESTAMP`, `INCONSISTENT_TIMESTAMPS`, `REVERSED_RANGE`, `INVALID_SEGMENT_TIMING`, `MISSING_INPUT_FILE`, `MALFORMED_INPUT_JSON` | Malformed or missing input structure |
| `UnsupportedInputError` | `UNSUPPORTED_SCHEMA_VERSION`, `UNSUPPORTED_CURRENCY`, `UNSUPPORTED_LANGUAGE`, `UNSUPPORTED_UNIT`, `UNSUPPORTED_FISCAL_PERIOD` | Input outside supported domain |
| `ConfigurationError` | `MISSING_CONFIG_FILE`, `MALFORMED_CONFIG_JSON`, `UNSUPPORTED_CONFIG_SCHEMA`, `POLICY_VIOLATION`, `INVALID_BUDGET` | Invalid/unsafe config (e.g. `allow_trade_actions=true`) |
| `BudgetExceededError` | `SEGMENT_BUDGET_EXCEEDED`, `LLM_CALL_BUDGET_EXCEEDED`, `LLM_TOKEN_BUDGET_EXCEEDED` | Input or execution exceeds fixed deterministic budget |
| `EvidenceVerificationError` | `SPAN_OUT_OF_BOUNDS`, `QUOTE_MISMATCH` | Proposed evidence span does not match verbatim source text |
