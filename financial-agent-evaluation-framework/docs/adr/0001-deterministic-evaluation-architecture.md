# ADR 0001: Deterministic Verification Core and Signed Tool Receipts

- **Status:** Accepted
- **Date:** 2026-11-28
- **Project:** Financial Agent Evaluation Framework (`Trading-Agentic`)

## Context

Evaluating financial agents purely via free-text similarity or LLM-as-judge creates three severe failure modes:
1. **Silent arithmetic or unit errors** (e.g., reporting `2500%` instead of `2500 bps` or miscomputing leverage ratios) often look plausible to LLM judges.
2. **Fabricated tool executions and citations** allow an agent to claim it queried an SEC filing or market quote when it actually hallucinated the value.
3. **Non-deterministic grading** breaks CI regression testing and prevents auditable baseline comparisons.

## Decision

1. **Isolate Pure Deterministic Graders from I/O:** Implement numeric, unit-normalized, citation-grounding, freshness, abstention, and tool-integrity graders as pure functions over typed Pydantic v2 schemas (`fin_eval.graders.*`, `fin_eval.evaluator`).
2. **Cryptographic/HMAC Tool Execution Receipts:** Have `MockToolRuntime` sign an HMAC-SHA256 `ToolExecutionReceipt` for every actual tool call (including `blocked_policy` attempts). Any claimed call without a matching, verified receipt triggers `FABRICATED_TOOL_EXECUTION` with score `0.0`.
3. **Treat Retrieved Text as Untrusted Data:** Flag all `EvidenceRecord` payloads as untrusted data and test prompt-injection resilience via `FailureInjectionEngine`.
4. **LLM-as-Judge Strictly Advisory:** Enforce `can_override_deterministic_fail: Literal[False] = False` on `LLMJudgeAssessment` and prohibit overriding authoritative deterministic hard fails in `combine_with_deterministic_authority`.

## Consequences

- **Positive:** 100% reproducible grading across machines and reruns; zero fabricated tool calls pass verification; clear failure taxonomy (`FailureType`) for debugging; fast offline execution (<1s for full suite).
- **Trade-off:** External agents must use a thin `FinancialAgentAdapter` to route tool calls through `MockToolRuntime` and populate structured `NumericClaim` and `CitationClaim` fields.
