# Data Contracts and Validation Specification

**Schema Version:** `1.0.0`  
**Implementation:** `src/strategy_sandbox/contracts.py`

All contracts are enforced via strict Pydantic v2 models (`extra="forbid"`, finite-float checks, UTC timezone enforcement).

## 1. Units, timestamps, and identifier conventions

| Dimension | Convention | Validation Rule |
|---|---|---|
| Currency / Cash / Price | USD (`float`) | Must be finite (`math.isfinite`); prices `> 0.0` |
| Rates / Costs | Basis points (`bps`) | `0.0 <= commission_bps <= 500.0`, `0.0 <= slippage_bps <= 500.0` |
| Exposure / Leverage | Dimensionless ratio (`exposure / equity`) | `0.0 < max_position_pct <= 1.0`, `0.0 < max_gross_leverage <= 2.0` |
| Timestamps | UTC ISO-8601 (`datetime`) | Naive timestamps rejected; normalized to UTC (`Z`) in canonical JSON |
| Identifiers (`dataset_id`, `spec_id`, `proposal_id`, `trial_id`, `review_id`) | ASCII slug | Regex `^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$` |
| Instrument Symbols | Uppercase synthetic ticker | Regex `^[A-Z0-9][A-Z0-9._-]{0,15}$` |
| Artifact Digests | SHA-256 hex | 64 lowercase hexadecimal chars over canonical UTF-8 JSON |

## 2. Canonical input contracts

### 2.1 `AssetBar` & `DatasetManifest`
- Each `AssetBar` enforces `high >= max(open, close)`, `low <= min(open, close)`, `volume >= 0`, and optional `note` (`<= 256` chars, treated as untrusted text and stripped before passing to strategy code).
- `DatasetManifest` enforces:
  - `provenance` in `{"synthetic_fixture", "approved_offline"}` (no live feeds or customer data).
  - Globally non-decreasing timestamps and strictly increasing timestamps per symbol.
  - All bar symbols declared in `symbols` and all declared symbols present in `bars`.
  - `sha256` computed over canonical bar records if omitted, or verified exact if provided.

### 2.2 `StrategySpec`
Defines `spec_id`, `target_symbols`, `initial_cash`, `commission_bps`, `slippage_bps`, `max_gross_leverage`, `max_position_pct`, `allow_short`, fixed `seed`, and typed read-only `params`.

### 2.3 `ExperimentBudget`
Hard execution bounds:
- `max_wall_time_sec` (default `2.0s`), `max_cpu_time_sec` (default `1.0s`)
- `max_memory_mb` (default `128`), `max_output_bytes` (default `65536`)
- `max_steps` (default `10000`), `max_code_bytes` (default `32768`), `max_ast_nodes` (default `2000`)
- `allow_network: Literal[False] = False`
- `allow_filesystem_write: Literal[False] = False`
- `allow_subprocess: Literal[False] = False`

### 2.4 `StrategyProposal`
Separates generated code (`code`, `code_sha256`, `author_type`, `model_id`) from untrusted `rationale` text and binds strictly to a `spec_id`.

## 3. Restricted Strategy API (`on_bar(ctx)`)

Generated strategy code must define:

```python
def on_bar(ctx) -> list[dict]:
    ...
```

- **Allowed imports**: `math`, `statistics` (configurable allowlist).
- **Exposed `ctx` properties** (all read-only except `ctx.state`):
  - `ctx.step: int`, `ctx.timestamp: str`
  - `ctx.current_bars: Mapping[str, BarView]` (`timestamp, symbol, open, high, low, close, volume`; `note` is never exposed)
  - `ctx.history(symbol, lookback=None) -> tuple[BarView, ...]` (strictly bars `0..ctx.step`)
  - `ctx.cash: float`, `ctx.equity: float`, `ctx.positions: Mapping[str, PositionView]`, `ctx.position_qty(symbol) -> float`
  - `ctx.params: Mapping[str, Any]`, `ctx.state: dict[str, Any]`, `ctx.rng: DeterministicRNG`
- **Returned order items** validate against `OrderIntent`: `symbol`, `side` (`"BUY" | "SELL"`), `quantity > 0`, `order_type` (`"MARKET"`), optional `reason` (`<= 160` chars).

## 4. Paper execution and accounting contract

- Market orders emitted on bar `t` execute at bar `t` close price adjusted by `slippage_bps`:
  - `BUY`: `fill_price = close * (1 + slippage_bps / 10_000)`
  - `SELL`: `fill_price = close * (1 - slippage_bps / 10_000)`
- `commission = quantity * fill_price * (commission_bps / 10_000)`
- **Exact accounting identity** checked on every bar (tolerance `1e-6`):
  - `equity = cash + sum(quantity_i * close_i)`
  - `equity - initial_cash == realized_pnl + unrealized_pnl - cumulative_commission`

## 5. Canonical outputs and error codes

- `TrialRecord`: immutable audit object containing `trial_id`, `status`, `code_sha256`, `dataset_sha256`, `input_bundle_sha256`, `output_sha256`, `checks`, `accounting`, `fills`, `rejected_orders`, `equity_curve`, `telemetry`, `runtime_env`, and `structured_logs`.
- `HumanReviewRecord`: binds `reviewer`, `decision` (`APPROVE | REJECT | REQUEST_CHANGES`), `trial_id`, `code_sha256`, and `output_sha256`.
- `PromotionDecision`: `promoted: bool`, `stage` (`PAPER_STAGING_APPROVED | REJECTED`), linked `review_id`, and hashes.
- **Typed Error Codes** (`errors.py`): `CONFIGURATION_ERROR`, `CONTRACT_VALIDATION_ERROR`, `DATASET_SAFETY_ERROR`, `STATIC_POLICY_ERROR`, `SANDBOX_TIMEOUT`, `RESOURCE_LIMIT_EXCEEDED`, `SECURITY_DENIAL`, `FUTURE_DATA_LEAKAGE`, `NONDETERMINISTIC_BEHAVIOR`, `ACCOUNTING_INVARIANT_VIOLATION`, `PROMOTION_DENIED`, `UNSUPPORTED_BACKEND`.

## 6. Fixtures catalog (`data/fixtures/`)

| Fixture | Category | Purpose |
|---|---|---|
| `reference_dataset.json` | Valid | 10-bar deterministic synthetic `SYNTH_A` OHLCV series |
| `reference_spec.json` | Valid | `SMA(2,4)` paper spec (`$100,000` cash, 5 bps comm, 10 bps slip, seed 42) |
| `reference_proposal.json` | Valid | Reference causal `on_bar(ctx)` implementation |
| `reference_expected.json` | Oracle | Exact hand-calculated expected fills, cash, PnL, and equity (`$101,137.0006`) |
| `invalid_dataset_ohlc.json` | Invalid | Violates `high >= max(open, close)` schema invariant |
| `malicious_dataset.json` | Boundary / Adversarial | Prompt-injection and `__import__('os').system(...)` strings in `bar.note` |
