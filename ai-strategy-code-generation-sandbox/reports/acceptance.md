# Acceptance Report — AI Strategy Code Generation Sandbox

**Generated:** 2026-11-28  
**Environment:** macOS-26.5.1-arm64 (`CPython 3.12.15`, `pydantic 2.14.4`, `pytest 8.4.2`, backend `subprocess_isolated`)  
**Raw Evidence Files:**
- [demo_results.json](demo_results.json)
- [benchmark_results.json](benchmark_results.json)
- [registry_snapshot/trials.jsonl](registry_snapshot/trials.jsonl)

> **Evidence provenance:** All measurements below are **actual observations** recorded on **synthetic offline fixtures** (`data/fixtures/reference_dataset.json`, `malicious_dataset.json`, `invalid_dataset_ohlc.json`). No live market feeds, real transactions, customer records, or production credentials were used.

---

## 1. Project-specific acceptance criteria

| Acceptance Criterion | Status | Observed Evidence |
|---|---|---|
| Sandbox denial tests pass | **PASS** | 7 parametrized attack vectors (`open()`, `socket`, `urllib`, `os.system`, `subprocess.Popen`, `__subclasses__`, `eval()`) denied at **both** Layer 1 (`FAILED_STATIC_POLICY`) and Layer 2/3 runtime (`FAILED_SANDBOX` / `SECURITY_DENIAL`) in `tests/test_sandbox_denial_and_limits.py`; host secret env vars (`BROKER_API_KEY`, `LIVE_ACCOUNT_TOKEN`) confirmed invisible to worker. |
| All experiments terminate within limits | **PASS** | Infinite loop killed in **0.407 s** (`SANDBOX_TIMEOUT`, budget `0.4 s`); 1.5M-int memory allocation killed in **0.160 s** (`RESOURCE_LIMIT_EXCEEDED`, budget `16 MB`); output flood blocked (`RESOURCE_LIMIT_EXCEEDED`, budget `2048 B`); normal 10-bar evaluation completes in **189.63 ms** median (`30.59 ms` median single sandbox run). |
| No code promoted without validation and review | **PASS** | `tests/test_malicious_dataset_and_governance.py` and `demo_results.json` verify: (1) unreviewed passing trial blocked (`unreviewed_promotion_blocked: true`), (2) `REJECT` and hash-mismatched reviews blocked, (3) tampered trial artifact blocked (`ARTIFACT_HASH_MISMATCH`), (4) failed trial blocked even with human `APPROVE`, (5) matching hash-bound human `APPROVE` promotes to `PAPER_STAGING_APPROVED`. |
| All required test scenarios pass (untested deps marked explicitly) | **PASS** | **30 / 30 pytest tests passed in 2.23 s**. Unavailable host capabilities (`docker_rootless` live execution and Linux `RLIMIT_AS`) are explicitly documented in Section 4 below and tested via explicit `UNSUPPORTED_BACKEND` handling. |
| README documents setup, demo, validation, assumptions, and limitations | **PASS** | Documented in `README.md`, `docs/architecture.md`, `docs/contracts.md`, `docs/integration.md`, `docs/runbook.md`, and `docs/adr/0001-sandbox-architecture.md`. |
| No real transactions, customer data, credentials, or proprietary/SAAT artifacts | **PASS** | Verified across `src/`, `tests/`, `data/fixtures/`, `config/`, `docs/`, and `reports/`; synthetic symbols (`SYNTH_A`) and fake unit-test env strings only. |

---

## 2. Test and validation matrix mapping

| Test Area | Required Scenario | Test / Script Evidence | Measured Result |
|---|---|---|---|
| Domain correctness | Infinite loop, resource abuse, attempted file/network access | `tests/test_sandbox_denial_and_limits.py` (13 test cases) | **13/13 PASS**; infinite loop `0.407s`, memory abuse `0.160s`, static + runtime `SECURITY_DENIAL` |
| Domain correctness | Reference oracle comparison | `tests/test_contracts_and_fixtures.py::test_reference_strategy_matches_hand_calculated_oracle` | **PASS**; final equity `$101,137.0006` vs oracle `$101,137.0006` (`max_accounting_identity_error = 0.00e+00`, tolerance `1e-6`) |
| Integration & resilience | Future-data leakage | `tests/test_leakage_determinism_accounting.py::test_future_data_leakage_detected_and_rejected` & `demo_results.json` | **PASS**; reference passes 2 checkpoints (4 probes: future-shock + prefix-truncation); synthetic leaky strategy rejected with `FAILED_LEAKAGE` / `FUTURE_DATA_LEAKAGE` |
| Boundary & failure behavior | Malicious instructions in dataset | `tests/test_malicious_dataset_and_governance.py` (2 test cases) | **PASS**; prompt-injection, `__import__('os').system`, and Unicode bidi `\u202e` rejected pre-execution (`FAILED_DATA_SAFETY`, `sandbox_invocations = 0`) |
| Reproducibility | Same versioned inputs/config & fixed seed | `tests/test_leakage_determinism_accounting.py` + `demo_results.json` (`replay_verification`) | **PASS**; deterministic across runs and replay reproduces identical `trial_id` (`trial-5a25ccc8126d-6b893d53`) and `output_sha256` (`6b893d53800a...`) |
| Operational review | Missing config, unsupported inputs/backend, CLI workflow | `tests/test_operational_and_cli.py` (4 test cases) | **PASS**; explicit `CONFIGURATION_ERROR`, `CONTRACT_VALIDATION_ERROR`, `UNSUPPORTED_BACKEND`, and non-zero CLI exits |

---

## 3. Observed benchmark measurements (`reports/benchmark_results.json`)

Measured over 5 full reference evaluations (`10` bars, `6` sandbox invocations per full evaluation: 1 primary + 1 determinism replay + 4 leakage probes):

| Metric | Mean | Median | Max | Budget / Target |
|---|---|---|---|---|
| Full evaluation wall time | 187.31 ms | 189.63 ms | 190.96 ms | `< 2000 ms` per sandbox run |
| Single sandbox execution wall time | 31.46 ms | 30.59 ms | 35.66 ms | `2000 ms` (`max_wall_time_sec`) |
| Peak traced Python memory | 116,102 B (~0.11 MB) | 116,102 B | 116,102 B | `128 MB` (`max_memory_mb`) |
| Output bytes (primary run) | 1,006 B | 1,006 B | 1,006 B | `65,536 B` (`max_output_bytes`) |

---

## 4. Explicitly untested / environment-unavailable capabilities

| Capability | Status on This Host | Reason & Mitigation |
|---|---|---|
| Live rootless Docker container execution (`Dockerfile` / `docker-compose.yml`) | **NOT RUN** | `docker` CLI/daemon is not installed on this workstation (`docker_available: false`). `DockerSandboxRunner` detects absence and fails explicitly with `UNSUPPORTED_BACKEND` (`test_docker_backend_reports_unsupported_explicitly_when_unavailable`). |
| OS-level `RLIMIT_AS` virtual memory cap | **NOT APPLIED ON MACOS** | `rlimit_as_applied: false` on macOS ARM64 due to CPython virtual reservation semantics; worker enforces memory budget via `tracemalloc` (`test_memory_abuse_terminated_within_budget`). Linux CI (`ubuntu-latest` in `.github/workflows/ci.yml`) applies both `RLIMIT_AS` and `tracemalloc`. |
| Production multi-tenant untrusted code execution | **OUT OF SCOPE** | Educational/research prototype only; requires hardware-virtualized microVMs (e.g., Firecracker/gVisor) plus separate security, legal, and risk review before any production use. |
