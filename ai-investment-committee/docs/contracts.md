# Data Contracts — AI Investment Committee

- **Contract Schema Version:** `1.0.0` (`SUPPORTED_SCHEMA_VERSION`)
- **Timestamp Semantics:** All timestamps (`created_at`, `as_of`, `published_at`, `approved_at`, `evaluated_at`) MUST be UTC ISO-8601 strings ending in `Z` or `+00:00` (e.g., `2026-11-28T09:00:00Z`). Naive or local-offset timestamps fail validation with `SchemaValidationError`.
- **Units:**
  - Monetary values (`*_usd`): US Dollars (`USD`), finite floating-point numbers. Non-USD currencies raise `UnsupportedInputError`.
  - Percentages (`*_pct`): Percentage points (`0.0` to `100.0`, e.g., `10.0` means `10%`, not `0.10`).
  - Ratios (`*_ratio`): Unitless `[0.0, 1.0]`.
  - Quantities & ADV (`quantity`, `average_daily_volume_shares`): Positive integers (`shares`).
  - Horizon (`horizon_days`): Positive integer (`days`).
  - Latency (`*_ms`): Integer milliseconds.

## 1. Canonical Input Schemas

### `CommitteeProposal`
| Field | Type | Constraints |
|---|---|---|
| `schema_version` | `str` | Must equal `"1.0.0"` |
| `proposal_id` | `str` | Non-empty identifier |
| `created_at`, `as_of` | `str` | UTC ISO-8601 timestamp |
| `execution_mode` | `str` | Must equal `"PAPER"` (`"LIVE"` raises `NoExecutionCapabilityError`) |
| `candidate_position` | `CandidatePosition` | `ticker` (`[A-Z0-9._-]{1,16}`), `sector`, `side` (`BUY`/`SELL`), `quantity > 0`, `limit_price_usd > 0`, `currency == "USD"`, `horizon_days > 0`, `0 <= estimated_volatility_annual_pct <= 500`, `average_daily_volume_shares > 0`, `thesis_summary` |
| `portfolio_state` | `PortfolioState` | `portfolio_id`, `as_of`, `nav_usd > 0`, `cash_usd >= 0`, `0 <= current_estimated_var_95_pct <= 100`, `holdings[]` |
| `risk_policy` | `RiskPolicy` | `schema_version == "1.0.0"`, `policy_id`, positive percentage/count caps, `allow_live_execution == False` |
| `research_briefs` | `ResearchBrief[]` | Non-empty list; unique `evidence_id` across all `snippets[]`; `stance_hint` in `{bullish, bearish, neutral}` |

### `CommitteeConfig`
| Field | Type | Constraints |
|---|---|---|
| `schema_version` | `str` | Must equal `"1.0.0"` |
| `config_id` | `str` | Non-empty config version ID |
| `seed` | `int` | `>= 0` fixed reproducibility seed |
| `adapter_mode` | `str` | `"deterministic_mock"` or `"custom_adapter"` |
| `allow_live_execution` | `bool` | Must be `false` |
| `strict_citation_mode` | `bool` | Default `true` |
| `require_human_approval` | `bool` | Must be `true` |
| `agent_budgets` | `Dict[role, AgentBudget]` | Required keys: `bull`, `bear`, `portfolio`, `risk` with positive `max_tool_calls`, `max_tokens`, `max_latency_ms`, `max_cost_usd` |

## 2. Deterministic Identifiers & Formulas

- `proposal_hash`: `SHA-256(canonical_json(proposal.model_dump()))` (64 lowercase hex chars).
- `config_hash`: `SHA-256(canonical_json(config.model_dump()))`.
- `decision_id`: `"DEC-" + SHA-256({"proposal_hash", "config_hash", "seed"})[:16].upper()`.
- Standalone incremental 1-day 95% VaR:
  $$\Delta \text{VaR}_{95\%} = \pm \left(\frac{\text{TradeNotional}}{\text{NAV}}\right) \cdot \left(\frac{\sigma_{\text{annual},\%}}{\sqrt{252}}\right) \cdot 1.6448536$$

## 3. Typed Output Contracts

- **`Claim`**: `claim_id`, `author_role`, `statement`, `evidence_ids`, `is_uncertain`, `uncertainty_reason`, `citation_status` (`VERIFIED` | `UNCERTAIN` | `FABRICATED`), `fabricated_evidence_ids`. **Invariant:** empty `evidence_ids` with `is_uncertain=False` is rejected at construction time.
- **`ThesisRecord`**: Bull thesis summary, `conviction_score`, `claims[]`, `injection_flags[]`.
- **`ChallengeRecord`**: Bear adversarial review, `dissent_level` (`LOW`/`MODERATE`/`HIGH`), `dissent_score`, `challenged_claim_ids[]`, `claims[]`, `injection_flags[]`.
- **`PortfolioReviewRecord`**: Pro-forma exposure metrics, `sizing_recommendation`, `claims[]`.
- **`RiskVerdictRecord`**: `verdict` (`PASS`/`VETO`), `non_overridable` (`True` when `VETO`), `checks[]`, `violated_rules[]`, `metrics`, `rationale`.
- **`HumanApprovalRecord`**: `approval_id`, `proposal_id`, `proposal_hash`, `reviewer_id`, `decision` (`APPROVE_PAPER`/`REJECT`), `rationale`, `approved_at`.
- **`DecisionRecord`**: Final state (`VETOED`, `AWAITING_HUMAN_APPROVAL`, `APPROVED_FOR_PAPER_ONLY`, `REJECTED_BY_HUMAN`, `HALTED_ERROR`), `execution_capability` (always `NONE_PAPER_ONLY`), plus all role records and optional `human_approval`.
- **`DeliberationReplayTrace`**: Full persisted audit bundle including `decision`, `agent_traces[]` (tool calls, tokens, latency, cost, injection flags), totals, and `runtime_metadata`.

## 4. Structured Error Catalog

| Error Class | `error_code` | Trigger |
|---|---|---|
| `SchemaValidationError` | `SCHEMA_VALIDATION_ERROR` | Missing field, wrong type, non-UTC timestamp, out-of-range value, uncited non-uncertain claim |
| `UnsupportedInputError` | `UNSUPPORTED_INPUT_ERROR` | Unsupported currency (`EUR`), unsupported `schema_version` (`2.0.0`), unsupported `adapter_mode` |
| `MissingConfigurationError` | `MISSING_CONFIGURATION_ERROR` | Missing/unreadable JSON file or missing decision ID in store |
| `NoExecutionCapabilityError` | `NO_EXECUTION_CAPABILITY` | `execution_mode="LIVE"`, `allow_live_execution=true`, or execution/override tool call |
| `ToolAccessDeniedError` | `TOOL_ACCESS_DENIED` | Agent calls a tool outside `ROLE_ALLOWED_TOOLS[role]` |
| `BudgetExceededError` | `BUDGET_EXCEEDED` | Agent exceeds `max_tool_calls`, `max_tokens`, or `max_cost_usd` |
| `AgentTimeoutError` | `AGENT_TIMEOUT` | Agent latency exceeds `max_latency_ms` |
| `RiskVetoBypassError` | `RISK_VETO_BYPASS_FORBIDDEN` | Any attempt to approve a `VETOED` proposal |
| `ProposalHashMismatchError` | `PROPOSAL_HASH_MISMATCH` | Human approval `proposal_hash` or `proposal_id` does not match canonical record |
| `DuplicateApprovalError` | `DUPLICATE_APPROVAL` | Reused `approval_id` or second approval on an already-finalized decision |

## 5. Fixture Inventory (`data/fixtures/`)

- `valid_reference_proposal.json` — Clean `PAPER` proposal (`ACME`) passing all policy rules.
- `reference_expected_output.json` — Independent hand-calculated oracle and tolerances (`percentage_abs=0.005`, `usd_abs=0.01`).
- `disagreement_fabricated_evidence.json` — High-dissent proposal (`NOVA`) used for both disagreement and fabricated-citation tests.
- `prompt_injection_risk_veto.json` — Untrusted brief with 7 injection directives + multi-rule policy breaches (`VOLT`).
- `boundary_inputs.json` — Exact policy boundary proposal (`EDGE`: `10.0%` position, `25.0%` sector, `10.0%` cash, `5.0%` ADV).
- `invalid_inputs.json` — 8 negative test cases covering forbidden live mode, negative quantity, bad timestamp, unsupported currency, invalid side, zero NAV, forbidden policy flag, and missing ID.
