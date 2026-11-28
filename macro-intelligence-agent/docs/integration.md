# Integration and Provenance — Macro Intelligence Agent

## 1. Repository Context (`Trading-Agentic`)

This project lives independently at `macro-intelligence-agent/` at the root of the `Trading-Agentic` repository alongside sibling projects:
- `ai-investment-committee/` (shares the same Python 3.9+ zero-dependency stdlib core + optional `[pydantic]` / `[dev]` packaging convention in `pyproject.toml`, SQLite replay log design, and offline research-only boundary).
- `ai-strategy-code-generation-sandbox/`, `earnings-call-intelligence-agent/`, `financial-agent-evaluation-framework/`, `trading-incident-investigation-agent/`, and the repository's existing research, RAG, sentiment, strategy discovery, and RL trading projects (independent packages; no cross-imports required).

Per architectural boundaries, `macro-intelligence-agent` has **no cross-project code imports** and can be consumed cleanly via:

1. **Typed Python Library API:** Import `MacroIntelligenceService`, `ReleaseArchive`, `AgentConfig`, and typed dataclasses from `macro_intelligence_agent`.
2. **CLI / JSON Envelope Interface:** Invoke `python3 -m macro_intelligence_agent brief|evaluate|replay` to exchange versioned JSON documents (`schema_version: "1.0.0"`).
3. **Pluggable `SummarizerAdapter` Protocol (`briefs.py`):** Downstream callers can inject an approved offline or sandboxed summarizer implementing `SummarizerAdapter` while preserving deterministic extraction, reconciliation, and post-generation `verify_brief` enforcement.

## 2. Downstream Integration Example (Adapter Boundary)

A multi-agent committee (such as `ai-investment-committee`) or an evaluation harness (such as `financial-agent-evaluation-framework`) can consume `AgentRunResult.to_dict()` as a read-only evidence record keyed by `metadata.run_id`, `metadata.as_of_utc`, and `brief.citations_index`, without sharing internal databases or mutable state.

## 3. Dependencies and Licensing

| Component | Dependency | License | Usage |
|---|---|---|---|
| Core runtime & tests | Python 3.9+ Standard Library (`sqlite3`, `dataclasses`, `decimal`, `datetime`, `hashlib`, `json`, `re`, `unittest`, `argparse`) | PSF License | Required for all core functionality |
| Optional schema extra (`[pydantic]`) | `pydantic>=2.7.0,<3.0.0` | MIT | Optional validation backend detection (`pydantic_adapter.py`) |
| Optional dev extra (`[dev]`) | `pytest`, `ruff`, `mypy` | MIT | Optional external test/lint/typecheck tooling |
| Project code | Original implementation in `src/`, `tests/`, `scripts/` | MIT (see `pyproject.toml`) | Independently authored for this plan |

## 4. Fixture Provenance and Clean-Room Statement

- All fixtures under `data/fixtures/` are **100% synthetic educational/research records** modeled on public macroeconomic release structures (CPI, FOMC statements, HICP, ECB rate, NFP).
- No proprietary employer/SAAT code, real customer data, live trading credentials, or live market-data vendor feeds exist anywhere in source, config, fixtures, logs, or reports.
- Live network access is hard-disabled in `ModelAdapterConfig` (`allow_live_network=false` raises `ConfigurationError` if set to `true`).
