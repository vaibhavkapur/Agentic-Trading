# Integration Guide — `Trading-Agentic` Ecosystem

## 1. Repository Layout (`Trading-Agentic`)

This project lives independently at `earnings-call-intelligence-agent/` at the root of the `Trading-Agentic` repository alongside sibling projects including:

- `earnings-call-intelligence-agent/` — **Implemented by this project**
- `ai-investment-committee/`
- `ai-strategy-code-generation-sandbox/`
- `financial-agent-evaluation-framework/`
- `macro-intelligence-agent/`
- `trading-incident-investigation-agent/`
- `autonomous-strategy-discovery-engine/`, `recursive-ai-research-platform/`, `multi-agent-ai-trading-platform/`, `financial-research-agent/`, `financial-sentiment-analysis-engine/`, `financial-intelligence-rag-platform/`, `reinforcement-learning-trading-engine/`

To remain independently runnable without cross-project coupling, this project maintains **zero hard imports** from sibling projects and exposes clean, versioned, independent adapters in `src/earnings_call_agent/adapters.py`.

## 2. Independent Adapter Boundaries

### 2.1 Research Note Export Adapter (`export_research_note_envelope`)
Converts an `AnalysisReport` into a compact, versioned JSON envelope (`envelope_version="1.0.0"`) designed for future downstream consumers such as:
- **`ai-investment-committee`**: Supplies verifiable guidance changes (`RAISED`, `LOWERED`, `REAFFIRMED`, `NARROWED`, `CONTRADICTORY`), uncertainty flags, staleness status, and evidence counts as a fundamental research memo input.
- **`financial-agent-evaluation-framework`**: Supplies deterministic `run_id`, `logical_digest`, `eval_results.json`, and injection-defense telemetry for cross-agent benchmarking.

Safety boundary: `export_research_note_envelope` hardcodes `"execution_mode": "research_only_no_orders"` and `"trade_action_permitted": False`. It cannot emit executable order instructions.

### 2.2 Optional LLM Extraction Provider Boundary (`LLMExtractorProtocol`)
External LLM providers (e.g., Anthropic, OpenAI, Gemini, or local open-weight models) can be plugged in without modifying domain logic by implementing:

```python
class LLMExtractorProtocol(Protocol):
    def propose_claims(
        self,
        sanitized_segment: SanitizedSegment,
        default_fiscal_period: str,
        seed: int,
    ) -> Sequence[ProposedClaim]:
        ...
```

Every `ProposedClaim` returned by an adapter passes through `run_budgeted_llm_extraction()`, which enforces:
1. Fixed `max_llm_calls` and `max_llm_tokens` budgets (`BudgetExceededError` on breach).
2. Rejection of any span overlapping a prompt-injection quarantined range.
3. Strict verbatim verification against `segment.text[char_start:char_end] == quoted_text`.
4. Canonical unit and fiscal period normalization.

## 3. Compatibility & Provenance Guarantees

- **Runtime compatibility:** Python >= 3.9 standard library only (no native extensions or network services required).
- **Optional dependencies:** `pydantic==2.9.2` and dev tools (`pytest`, `ruff`, `mypy`) are declared as optional extras in `pyproject.toml`.
- **Clean-room provenance:** Zero dependency on private employer code, SAAT artifacts, live brokerages, or real customer records.
