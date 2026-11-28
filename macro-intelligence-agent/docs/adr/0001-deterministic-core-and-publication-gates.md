# ADR-0001: Deterministic Core Runtime, Strict Publication Gates, and Untrusted-Text Isolation

- **Status:** Accepted
- **Date:** 2026-11-28
- **Project:** Macro Intelligence Agent (`macro-intelligence-agent`)

## Context

Macroeconomic release analysis is vulnerable to three failure modes common in agentic prototypes:

1. **Look-ahead / embargo leakage:** Historical evaluations silently include revised vintages or future releases that were not publicly available at the stated cutoff.
2. **Unverified synthesis and fabrication:** Optional LLM summarization can invent consensus figures, conflate incompatible periodicities (e.g., `% MoM` vs `% YoY`), or smooth over conflicting wire reports.
3. **Environment drift and prompt injection:** Heavy runtime dependencies hinder offline reproducibility, and retrieved press/release text may contain adversarial override instructions.

## Decision

1. **Zero-dependency Python 3.9+ stdlib core with optional Pydantic adapter:** Core contracts (`models.py`, `config.py`) use frozen `dataclasses`, exact `Decimal` arithmetic, strict timezone-aware UTC `datetime` parsing, and SQLite (`sqlite3`). An optional `[pydantic]` extra is declared in `pyproject.toml` and surfaced via `pydantic_adapter.py`, matching the offline-first pattern used across `Trading-Agentic`.
2. **Defense-in-depth publication gates:** Every archived release stores `available_at = max(published_at, embargo_until)` in canonical UTC ISO-8601 format. Both SQLite queries (`available_at <= as_of_utc`) and in-memory post-filtering + post-generation verification (`verification.verify_brief`) independently enforce the cutoff.
3. **Offset-preserving untrusted-text quarantine:** `security.sanitize_untrusted_release_text` detects prompt-injection / override spans and masks them with equal-length spaces (`quarantine` mode) or raises `UntrustedInstructionError` (`reject` mode). Preserving exact character lengths guarantees legitimate citation offsets `[char_start:char_end]` never drift from `raw_text`.
4. **Strict separation of model synthesis and deterministic verification:** Narrative summary generation sits behind the `SummarizerAdapter` protocol (defaulting to an offline, fixed-budget `DeterministicMockSummarizer` with `allow_live_network=false`), while figure grounding, unit compatibility, conflict abstention, revision diffing, and citation verification execute deterministically.

## Consequences

- **Positive:** Bit-for-bit reproducible runs, `0.03s` test execution in offline Python 3.9+ environments, 100% verifiable character-span citations, and explicit abstention on ambiguity.
- **Trade-offs:** Free-text extraction without structured `reported_metrics` currently relies on deterministic regex patterns for core series (`US_CPI_HEADLINE`, `US_CPI_CORE`, `US_NFP`, `FED_FUNDS_TARGET_UPPER`) and a curated policy-stance lexicon rather than open-domain semantic parsing. Live LLM providers remain disabled and explicitly untested in this prototype.
