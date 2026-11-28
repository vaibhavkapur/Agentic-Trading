# ADR-0001: Deterministic Verification Core, Zero-Dependency Runtime, and Untrusted-Text Quarantine

**Status:** Accepted  
**Date:** 2026-11-28  
**Project:** `earnings-call-intelligence-agent`

## Context

`plan.md` specifies an offline research prototype for extracting verifiable financial claims and guidance changes from segmented earnings-call transcripts with exact evidence spans, strict abstention without support, prompt-injection resilience, and deterministic reproducibility.

The suggested stack lists Python, Pydantic, optional LLM provider, and optional vector search, with explicit guidance to adapt choices to the environment with documented rationale. On the target verification environment (Python 3.9.6 without external network access), requiring third-party runtime packages or live LLM APIs would break offline reproducibility from a clean checkout.

## Decisions

1. **Zero-external-runtime-dependency Python 3.9+ core (`src/earnings_call_agent/`):**
   - Implement canonical data models, strict runtime validation, unit/period normalization, and structured error codes using Python's standard library (`dataclasses`, `enum`, `typing`, `re`, `json`, `hashlib`, `datetime`).
   - Keep `pyproject.toml` and `requirements-lock.txt` with pinned optional extras (`pydantic==2.9.2`, `pytest==8.3.3`, `ruff==0.6.9`, `mypy==1.11.2`).
   - Write automated tests with `unittest.TestCase` so they run both with built-in `python3 -m unittest` and with `pytest`.

2. **Separation of model calls from deterministic verification & policy:**
   - Default `extraction_mode` is `"deterministic"`, using pure domain rules isolated from I/O.
   - Optional LLM extraction is exposed via `LLMExtractorProtocol` and wrapped by `run_budgeted_llm_extraction()`, which enforces fixed call/token budgets and runs mandatory verbatim substring verification (`build_verified_evidence`) before any claim enters domain state.
   - `allow_trade_actions` is enforced as `False` in `AgentConfig` and in all exported reports/envelopes.

3. **Offset-preserving prompt-injection quarantine:**
   - All transcript text is treated strictly as untrusted data.
   - Offending sentences matching instruction-override, system-prompt, tool-spoofing, exfiltration, or trade-action patterns are replaced in-place with spaces of identical character length (`SanitizedSegment.sanitized_text`).
   - This guarantees injected fake numbers cannot be extracted while preserving exact `[char_start, char_end)` character offsets against the original `TranscriptSegment.text` for legitimate neighboring sentences.

## Consequences

- **Positive:** 100% reproducible offline execution and replay on any Python 3.9+ environment with zero external API keys or network calls; mathematical guarantee that every verified claim quotes its source verbatim.
- **Trade-off:** Rule-based deterministic extraction handles standard English earnings-call phrasing well (1.00 F1 on synthetic gold fixtures) but will miss highly unusual paraphrases or non-USD / non-English disclosures unless paired with a verified LLM adapter in `hybrid` mode.
- **Not run in offline mode:** Live third-party LLM provider calls and optional vector database retrieval are outside offline verification and explicitly documented as untested in `reports/acceptance.md`.
