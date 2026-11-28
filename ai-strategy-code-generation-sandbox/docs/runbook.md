# Operator and Developer Runbook

## 1. Local setup (from clean checkout)

```bash
cd ai-strategy-code-generation-sandbox
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
```

Using `uv` (offline-compatible when wheels are cached):

```bash
cd ai-strategy-code-generation-sandbox
python3 -m uv venv --python 3.12 .venv
python3 -m uv pip install --python .venv/bin/python -r requirements.lock.txt
```

## 2. Running validation and the reproducible demo

```bash
# Run full unit, integration, security, and operational test suite
PYTHONPATH=src .venv/bin/pytest -v

# Run end-to-end demo + adversarial checks + latency benchmark (writes reports/*.json)
PYTHONPATH=src .venv/bin/python scripts/run_demo_and_benchmarks.py
```

## 3. CLI walkthrough (evaluate -> review -> promote)

```bash
# 1. Validate configuration
PYTHONPATH=src .venv/bin/python -m strategy_sandbox.cli validate-config \
  --config config/default_sandbox_config.json

# 2. Evaluate reference proposal and persist to registry
PYTHONPATH=src .venv/bin/python -m strategy_sandbox.cli run-trial \
  --config config/default_sandbox_config.json \
  --spec data/fixtures/reference_spec.json \
  --dataset data/fixtures/reference_dataset.json \
  --proposal data/fixtures/reference_proposal.json \
  --reference data/fixtures/reference_expected.json \
  --registry-dir reports/tmp/demo_reg

# 3. Record human review bound to the trial's code and output SHA-256 hashes
PYTHONPATH=src .venv/bin/python -m strategy_sandbox.cli review \
  --registry-dir reports/tmp/demo_reg \
  --trial-id trial-5a25ccc8126d-6b893d53 \
  --review-id rev-001 \
  --reviewer quant-reviewer \
  --decision APPROVE \
  --notes "Verified oracle match, leakage checks, and accounting identity."

# 4. Promote to PAPER_STAGING_APPROVED
PYTHONPATH=src .venv/bin/python -m strategy_sandbox.cli promote \
  --registry-dir reports/tmp/demo_reg \
  --trial-id trial-5a25ccc8126d-6b893d53
```

## 4. Diagnostics and recovery procedures

| Symptom / Exit Code | Root Cause | Recovery Action |
|---|---|---|
| CLI exit `3` with `CONFIGURATION_ERROR` | Missing config file, malformed JSON, or schema violation | Restore or validate `config/default_sandbox_config.json` via `validate-config`. Never bypass validation. |
| `status: "FAILED_DATA_SAFETY"` | Malicious instruction, prompt injection, or bidi/control Unicode found in dataset metadata | Quarantine dataset, inspect `checks[0].details.findings`, sanitize source ingestion pipeline before re-running. |
| `status: "FAILED_STATIC_POLICY"` | Disallowed import, banned builtin, dunder access, or AST/size budget exceeded | Inspect `checks[1].details.violations`; rewrite strategy strictly against `docs/contracts.md` restricted API. |
| `status: "FAILED_SANDBOX"` (`SANDBOX_TIMEOUT` / `RESOURCE_LIMIT_EXCEEDED`) | Infinite loop, memory spike, or stdout flood exceeded `ExperimentBudget` | Inspect `telemetry.primary_exec`; optimize strategy loop/allocations or adjust budget only with documented risk review. |
| `status: "FAILED_SANDBOX"` (`UNSUPPORTED_BACKEND`) | `sandbox_backend: "docker_rootless"` configured on host without Docker | Switch `sandbox_backend` to `"subprocess_isolated"` or install rootless Docker/Podman and build `Dockerfile`. |
| `status: "FAILED_DETERMINISM"` | Strategy output varied across identical seeded runs | Replace nondeterministic sources (unordered sets, memory IDs, clocks) with `ctx.rng` and sorted iteration. |
| `status: "FAILED_LEAKAGE"` | Orders at `0..cp` changed under future-shock or prefix-truncation probes | Remove lookahead feature or causal boundary violation; inspect `checks[*].details.checkpoints_tested`. |
| `PROMOTION_DENIED` | Trial failed checks, artifact JSON was tampered with, or matching human `APPROVE` review is missing | Run `TrialRegistry.verify_trial_integrity(trial_id)`, resolve failed gates, re-run trial, and record a fresh hash-bound human review. |

## 5. Optional Docker rootless execution (hosts with Docker installed)

```bash
docker compose build
docker compose run --rm strategy-sandbox validate-config --config config/default_sandbox_config.json
```

> **Security reminder:** Containers alone are not a complete security boundary against untrusted code. Keep `network_mode: none`, `read_only: true`, `cap_drop: [ALL]`, non-root user, and add VM-level isolation before running untrusted third-party code in shared environments.
