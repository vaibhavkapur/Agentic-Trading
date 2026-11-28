# AI Investment Committee

Evidence-based multi-agent governance prototype for **paper** investment proposals. Orchestrates isolated **Bull**, **Bear**, **Portfolio**, and **Independent Risk** reviews with strict citation enforcement, prompt-injection quarantine, non-overridable deterministic risk vetoes, SHA-256 hash-bound human approval, and SQLite deliberation replay.

> **Scope & Safety Notice:** Educational and research prototype for offline, mock, and paper workflows only. Agent consensus is **not** independent evidence; human review is mandatory. Live capital, order routing, real customer records, production credentials, and proprietary employer/SAAT artifacts are strictly excluded.

## Quickstart

### Prerequisites
- Python **3.9+** (verified on Python `3.9.6` on macOS arm64 with SQLite `3.51.0`).
- Zero required third-party runtime dependencies (uses Python standard library only for deterministic offline reproducibility; see [ADR-001](docs/adr-001-deterministic-policy-and-contracts.md)).

### Run the Reproducible Demo
```bash
cd ai-investment-committee
python3 scripts/run_demo.py
```

### Run Full Validation & Acceptance Suite
```bash
cd ai-investment-committee
python3 scripts/run_acceptance.py
```
Or run unit/integration tests directly:
```bash
cd ai-investment-committee
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### CLI Walkthrough
```bash
cd ai-investment-committee

# 1. Run deliberation on the synthetic reference proposal
PYTHONPATH=src python3 -m ai_investment_committee run \
  --proposal data/fixtures/valid_reference_proposal.json

# 2. List persisted deliberations in SQLite
PYTHONPATH=src python3 -m ai_investment_committee list

# 3. Record human approval bound to the canonical proposal SHA-256 hash
PYTHONPATH=src python3 -m ai_investment_committee approve \
  --decision-id DEC-D5597349168D5D32 \
  --approval-id HUMAN-APP-001 \
  --proposal-id PROP-2026-001 \
  --proposal-hash 5840dcc326d3c1c05af9bc03c8223ccb2699185e263fee3f2884b89d72b963bc \
  --reviewer-id pm-reviewer-01 \
  --decision APPROVE_PAPER \
  --rationale "Reviewed bull/bear dissent and deterministic PASS verdict; paper ledger only."

# 4. Replay deliberation and verify exact logical & budget match
PYTHONPATH=src python3 -m ai_investment_committee replay --decision-id DEC-D5597349168D5D32

# 5. Evaluate dissent, citations, and cost
PYTHONPATH=src python3 -m ai_investment_committee evaluate --decision-id DEC-D5597349168D5D32
```

## Observed Demo & Validation Output (Synthetic Fixtures)

From the measured run recorded in [`reports/test_results.json`](reports/test_results.json), [`reports/baseline_comparison.json`](reports/baseline_comparison.json), and [`reports/demo_run_summary.json`](reports/demo_run_summary.json):

- **Automated test suite:** `18 / 18` tests passed in `41.27 ms` (`0` failures, `0` errors).
- **Reference proposal (`PROP-2026-001`):**
  - `decision_id`: `DEC-D5597349168D5D32`
  - `proposal_hash`: `5840dcc326d3c1c05af9bc03c8223ccb2699185e263fee3f2884b89d72b963bc`
  - Independent oracle comparison: **12 / 12** portfolio & risk metrics matched with `0.0` absolute difference.
  - Risk verdict: `PASS` -> `AWAITING_HUMAN_APPROVAL` -> `APPROVED_FOR_PAPER_ONLY` (`execution_capability: NONE_PAPER_ONLY`).
  - Replay exact match: `true` (`13` tool calls, `2020` simulated tokens, `$0.0201` simulated budget cost).
  - Duplicate approval blocked: `true` (`DUPLICATE_APPROVAL`).
- **Agent disagreement & fabricated evidence (`PROP-2026-002-DISAGREE`):**
  - Clean run records `HIGH` dissent (`dissent_score = 0.85`).
  - Fabricated citation (`EV-NONEXISTENT-404`) caught by deterministic auditor -> marked `FABRICATED` / `is_uncertain=true` -> deterministic risk `VETO` (`MAX_FABRICATED_CITATIONS`).
- **Prompt injection & risk veto (`PROP-2026-003-INJECT-VETO`):**
  - `7` prompt-injection directive matches quarantined in untrusted brief snippets.
  - Deterministic risk `VETO` triggered across 6 violated rules (`MAX_SINGLE_POSITION_WEIGHT_PCT`, `MAX_SECTOR_WEIGHT_PCT`, `MIN_CASH_RESERVE_PCT`, `MAX_ESTIMATED_VAR_95_PCT`, `MAX_ADV_PARTICIPATION_PCT`, `MIN_VERIFIED_CITATION_RATIO`).
  - Human approval veto-bypass attempt rejected (`RISK_VETO_BYPASS_FORBIDDEN`).
- **Agent timeout (`bear` delayed `2500ms > 1500ms` budget):**
  - Rejected explicitly with `AGENT_TIMEOUT`; nothing persisted silently.

## Project Layout

```text
ai-investment-committee/
├── config/
│   ├── committee_default.json
│   └── risk_policy_default.json
├── data/fixtures/
│   ├── boundary_inputs.json
│   ├── disagreement_fabricated_evidence.json
│   ├── invalid_inputs.json
│   ├── prompt_injection_risk_veto.json
│   ├── reference_expected_output.json
│   └── valid_reference_proposal.json
├── docs/
│   ├── adr-001-deterministic-policy-and-contracts.md
│   ├── architecture.md
│   ├── contracts.md
│   ├── integration.md
│   └── runbook.md
├── reports/
│   ├── acceptance.md
│   ├── baseline_comparison.json
│   ├── demo_run_summary.json
│   └── test_results.json
├── scripts/
│   ├── run_acceptance.py
│   └── run_demo.py
├── src/ai_investment_committee/
│   ├── agents.py
│   ├── cli.py
│   ├── errors.py
│   ├── hashing.py
│   ├── models.py
│   ├── replay.py
│   ├── risk_engine.py
│   ├── sanitization.py
│   ├── service.py
│   ├── state_machine.py
│   ├── storage.py
│   └── tools.py
├── tests/
│   ├── test_boundary_failures_and_ops.py
│   ├── test_contracts_and_fixtures.py
│   ├── test_domain_agents_and_evidence.py
│   ├── test_integration_security_and_veto.py
│   └── test_replay_and_reproducibility.py
├── plan.md
├── pyproject.toml
└── README.md
```

## Documentation & Evidence Links

- **Acceptance Evidence:** [`reports/acceptance.md`](reports/acceptance.md)
- **Architecture & Invariants:** [`docs/architecture.md`](docs/architecture.md)
- **ADR-001:** [`docs/adr-001-deterministic-policy-and-contracts.md`](docs/adr-001-deterministic-policy-and-contracts.md)
- **Data Contracts & Error Codes:** [`docs/contracts.md`](docs/contracts.md)
- **Integration Boundaries:** [`docs/integration.md`](docs/integration.md)
- **Operator & Developer Runbook:** [`docs/runbook.md`](docs/runbook.md)

## Assumptions, Provenance, Licenses & Known Limitations

- **Fixtures & Provenance:** All proposals, tickers (`ACME`, `NOVA`, `VOLT`, `EDGE`, `INDX`, `HLTH`, `TECH`, `UTIL`), portfolios, and research briefs in `data/fixtures/` are **100% synthetic** and authored for this prototype. No real market feeds, customer data, or proprietary employer/SAAT data are used.
- **Dependencies & Licenses:** Core runtime depends solely on the Python Standard Library (PSF License). Optional extras (`pydantic`, `pytest`, `ruff`, `mypy`) in `pyproject.toml` are MIT-licensed and not required for offline execution.
- **Assumptions & Limitations:**
  - Incremental VaR uses a simplified standalone 1-day 95% parametric approximation ($z = 1.6448536$, $252$ trading days) ignoring cross-asset covariance; it is an educational reference oracle, not a production risk model.
  - Only `USD`-denominated `PAPER` proposals (`BUY`/`SELL`) are supported; FX conversion, options/derivatives, short-margin borrow, and multi-currency portfolios are unsupported and raise explicit errors.
  - Token counts, latencies, and USD budgets in `DeterministicMockAdapter` are deterministic estimates for budget-accounting tests, not billed API calls to a live LLM provider.
  - Live LLM adapters and optional `pydantic` extras are **not tested** in this offline environment (documented explicitly in [`reports/acceptance.md`](reports/acceptance.md)).
