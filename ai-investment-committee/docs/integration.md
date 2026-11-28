# Integration Boundaries — AI Investment Committee

## 1. Repository Context (`Trading-Agentic`)

This project lives independently at `ai-investment-committee/` at the root of the `Trading-Agentic` repository alongside twelve sibling projects:
- `earnings-call-intelligence-agent/`
- `macro-intelligence-agent/`
- `trading-incident-investigation-agent/`
- `ai-strategy-code-generation-sandbox/`
- `financial-agent-evaluation-framework/`
- `autonomous-strategy-discovery-engine/`, `recursive-ai-research-platform/`, `multi-agent-ai-trading-platform/`, `financial-research-agent/`, `financial-sentiment-analysis-engine/`, `financial-intelligence-rag-platform/`, `reinforcement-learning-trading-engine/`

Accordingly, `ai-investment-committee` is implemented as a self-contained, independently runnable package with zero fragile cross-directory imports.

## 2. Clean Adapter Interfaces for Future Sibling Integration

1. **Upstream Research Brief Producers** (e.g., `earnings-call-intelligence-agent`, `macro-intelligence-agent`):
   - Emit JSON conforming to `ResearchBrief` / `EvidenceSnippet` in [`docs/contracts.md`](contracts.md).
   - All imported brief text crosses the `sanitization.py` untrusted-data boundary automatically.
2. **Downstream Evaluation Frameworks** (e.g., `financial-agent-evaluation-framework`):
   - Consume `DeliberationReplayTrace` and `EvaluationMetrics` JSON exported from SQLite or CLI (`ai-committee replay` / `ai-committee evaluate`).
3. **Optional Pluggable LLM Adapter (`LLMAdapter` Protocol in `src/ai_investment_committee/agents.py`):**
   - Implement `generate_bull_thesis(...) -> AdapterResponse` and `generate_bear_challenge(...) -> AdapterResponse`.
   - Inject via `InvestmentCommitteeService(..., adapter=my_adapter)` with `config.adapter_mode = "custom_adapter"`.
   - Even with a custom LLM adapter, **Portfolio** exposure math, **Citation Auditing**, **Independent Risk Verdict**, and **Hash-Bound Human Approval** remain strictly deterministic and non-overridable.

## 3. Excluded Integrations

- No brokerage, exchange, OMS/EMS, or live order-routing SDKs.
- No external network calls or live LLM API credentials in source, tests, or CI.
- Zero dependency on private employer or SAAT code, data, or infrastructure.
