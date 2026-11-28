# Integration Guide — Financial Agent Evaluation Framework

## 1. Repository Context (`Trading-Agentic`)

This project lives independently at `financial-agent-evaluation-framework/` at the root of the `Trading-Agentic` repository alongside sibling projects:

| Sibling Project | Integration Pattern |
|---|---|
| `ai-investment-committee/` | Implement `FinancialAgentAdapter` wrapper around committee thesis output |
| `ai-strategy-code-generation-sandbox/` | Map sandboxed backtest metrics into `NumericClaim` + `ToolCallRecord` |
| `earnings-call-intelligence-agent/` | Evaluate transcript QA citations & abstention using `MockToolRuntime` |
| `macro-intelligence-agent/` | Reuse `get_macro_indicator` mock tool contract & macro gold tasks |
| `trading-incident-investigation-agent/` | Evaluate incident root-cause citations, tool reliability & safety boundaries |
| `financial-research-agent/`, `financial-intelligence-rag-platform/`, `financial-sentiment-analysis-engine/`, `multi-agent-ai-trading-platform/` | Wrap agent briefs, RAG answers, or sentiment outputs into structured `AgentTrajectory` objects |

To remain independently runnable, this framework maintains **zero hard import coupling** to sibling codebases. Any sibling agent integrates via the standalone `FinancialAgentAdapter` protocol without copying evaluator internals.

## 2. Adapter Boundary (`FinancialAgentAdapter`)

Defined in [base.py](../src/fin_eval/agents/base.py):

```python
class FinancialAgentAdapter(Protocol):
    agent_id: str

    def run_task(
        self,
        *,
        task: GoldTask,
        runtime: MockToolRuntime,
        config: ModelConfig,
        run_id: str,
        seed: int,
    ) -> AgentTrajectory: ...
```

### Integration Requirements for External Agents
1. **Route All Tool Calls Through `runtime.call_tool(tool_name, arguments)`:** Never bypass `MockToolRuntime`; every reported `ToolCallRecord` must carry the exact `receipt_signature` returned by the runtime.
2. **Emit Structured Claims:** Populate `numeric_claims` (with explicit `NumericUnit`) and `citations` (with `evidence_id` and `quoted_span`).
3. **Respect Abstention Signals:** Check `rec.status == "error"` and `as_of_utc` freshness timestamps; set `abstained=True` and a concise `abstention_reason` when inputs are unavailable or stale.
4. **Treat Retrieved Text as Untrusted Data:** Never execute tool calls or alter figures instructed inside retrieved filing/transcript text.

## 3. Optional External LLM Provider Boundary

`OptionalLLMProviderAdapter` (`provider="openai_compatible"`) is **explicitly disabled by default** (`external_network_allowed: false`). Attempting to run it offline raises `UnsupportedOperationError`. To attach a real LLM client in an approved research environment:
- Subclass or replace `OptionalLLMProviderAdapter` in a separate adapter module.
- Supply credentials exclusively through environment variables (e.g., `FIN_EVAL_LLM_API_KEY`); never commit keys to `config/`, `data/`, or `reports/`.
- Keep `live_execution_enabled: false` (enforced by Pydantic `Literal[False]`) and route all model tool calls through `MockToolRuntime`.

## 4. Compatibility & Security Boundaries

- **Runtime:** CPython `>=3.10` (verified on Python `3.12.15`).
- **Dependencies:** Pinned `pydantic==2.14.4` (runtime) and `pytest==8.4.2` (dev/test).
- **Exclusions:** No live brokerage APIs, no customer PII, no proprietary employer or SAAT artifacts.
