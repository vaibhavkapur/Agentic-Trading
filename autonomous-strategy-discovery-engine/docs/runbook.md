# Operator Runbook

Run the commands in this guide from `autonomous-strategy-discovery-engine/`. See the [project README](../README.md) for prerequisites.

## 1. Standard Operations

### Setup & Verification on Clean Checkout
```bash
bash scripts/setup.sh
bash scripts/validate.sh
```

### Run Reproducible Discovery Demo
```bash
bash scripts/demo.sh
```
Outputs are written to `reports/demo_run/`:
- `leaderboard.md` & `leaderboard.json` (all baselines, eligible, rejected, and failed candidates with uncertainty intervals)
- `trial_ledger.sqlite` & `trials.jsonl` (complete append-only trial audit log)
- `split_manifest.json` (immutable split boundaries & hash)
- `health_metrics.json` (run health, failure, and decision counts)
- `packages/<strategy_id>/` (cryptographically fingerprinted strategy review packages)

### Verify Bit-for-Bit Reproducibility
```bash
bash scripts/reproduce.sh
```

## 2. Independent Review Workflow (Paper Sandbox Only)

1. Verify package cryptographic integrity:
   ```bash
   PYTHONPATH=src python3 -m asde.cli verify-package --package reports/demo_run/packages/<strategy_id>
   ```
2. Inspect `evaluation_evidence.json`, `split_manifest.json`, and `leaderboard.md`:
   - Confirm `holdout_reads_during_selection == 0`.
   - Confirm `primary_cost_scenario != "zero_cost_reference"` and check `stressed_2x` / `severe_3x` cost sensitivity.
   - Confirm `dsr_probability`, `bh_fdr_q_value`, bootstrap Sharpe/CAGR 95% CIs, drawdown, and turnover.
3. Record independent decision (reviewer must be a human distinct from `asde_engine`):
   ```bash
   PYTHONPATH=src python3 -m asde.cli review \
     --package reports/demo_run/packages/<strategy_id> \
     --reviewer "<human_reviewer_id>" \
     --decision APPROVE_PAPER_ONLY \
     --rationale "<documented review rationale>"
   ```

## 3. Health Metrics, Failure Modes & Safe Fallback

| Signal / Error | Meaning | Operator Response / Safe Fallback |
|---|---|---|
| `MANIFEST_INTEGRITY_ERROR` | Dataset CSV, split manifest, or exported package failed SHA-256 verification. | Halt immediately. Do not evaluate or promote. Regenerate verified fixture or investigate tampering. |
| `LOOK_AHEAD_VIOLATION` | Signal attempted `< 1` bar lag or market bar `available_time_utc` leaks into future execution bar. | Candidate is auto-rejected (`FAILED` in ledger). Audit upstream data timestamps before retrying. |
| `HOLDOUT_LEAKAGE_VIOLATION` | Component attempted to read holdout test split prior to selection lock. | Run halts / attempt blocked and logged. Treat split as tainted if leaked externally; create a new out-of-time holdout. |
| `candidates_eligible_for_review == 0` | No candidate survived cost stress, turnover/drawdown caps, and DSR multiple-testing adjustment. | **Expected safe fallback.** Do NOT relax DSR or cost realism to force a winner; stay in cash/baseline and refine hypotheses. |
| `GOVERNANCE_VIOLATION` | Attempt to enable live execution, bypass review, or self-approve. | Blocked fail-closed. Escalate to risk/engineering governance owners. |
