# Integration and Adapter Boundaries

## 1. Repository context (`Trading-Agentic`)

This project lives independently at `ai-strategy-code-generation-sandbox/` at the root of the `Trading-Agentic` repository alongside sibling projects including:

- `ai-investment-committee/`
- `earnings-call-intelligence-agent/`
- `financial-agent-evaluation-framework/`
- `macro-intelligence-agent/`
- `trading-incident-investigation-agent/`
- `autonomous-strategy-discovery-engine/`, `recursive-ai-research-platform/`, `multi-agent-ai-trading-platform/`, `financial-research-agent/`, `financial-sentiment-analysis-engine/`, `financial-intelligence-rag-platform/`, `reinforcement-learning-trading-engine/`

To avoid fragile cross-project coupling, this project is delivered as a **self-contained, independently runnable Python package** (`strategy_sandbox`) with clean typed adapter boundaries ready for cross-project integration.

## 2. Reusable adapter interfaces

| Interface | Location | Integration Role |
|---|---|---|
| `SandboxRunnerProtocol` | `src/strategy_sandbox/sandbox_runner.py` | Plug in alternative isolation backends (e.g., rootless Docker, Podman, Firecracker, gVisor) without modifying evaluation or accounting logic. |
| `ExperimentEvaluator` | `src/strategy_sandbox/verifier.py` | Callable evaluation service for upstream LLM code generators (e.g., `ai-investment-committee`) or benchmark suites (e.g., `financial-agent-evaluation-framework`). |
| `PaperPortfolioEngine` | `src/strategy_sandbox/paper_engine.py` | Pure, zero-I/O deterministic paper execution and double-entry accounting state machine usable standalone in backtest or evaluation harnesses. |
| `TrialRegistry` | `src/strategy_sandbox/registry.py` | Append-only SHA-256 ledger (`trials.jsonl`, `reviews.jsonl`, `promotions.jsonl`) consumable by audit dashboards or incident-investigation agents (`trading-incident-investigation-agent`). |
| CLI (`strategy-sandbox`) | `src/strategy_sandbox/cli.py` | Language-agnostic JSON stdout/stderr CLI (`validate-config`, `run-trial`, `review`, `promote`) for external orchestrators and CI pipelines. |

## 3. Clean-room and scope guarantees

- Zero dependency on any private, employer, or SAAT code, datasets, or credentials.
- No live broker connectors, order-routing gateways, or network clients are implemented or enabled (`allow_live_execution: Literal[False] = False`, `allow_network: Literal[False] = False`).
- All runtime dependencies are open-source (MIT/Apache/PSF): Python 3.12 stdlib, `pydantic` (MIT), and `pytest` (MIT, dev-only).
