# Integration, Dependencies, and Provenance

## 1. Repository Context (`Trading-Agentic`)

This project lives at `trading-incident-investigation-agent/` at the root of the `Trading-Agentic` repository alongside sibling projects including:

- `ai-investment-committee/`
- `ai-strategy-code-generation-sandbox/`
- `earnings-call-intelligence-agent/`
- `financial-agent-evaluation-framework/`
- `macro-intelligence-agent/`
- `autonomous-strategy-discovery-engine/`, `recursive-ai-research-platform/`, `multi-agent-ai-trading-platform/`, `financial-research-agent/`, `financial-sentiment-analysis-engine/`, `financial-intelligence-rag-platform/`, `reinforcement-learning-trading-engine/`

Per the implementation plan, this project is designed as a **standalone, independently runnable package** with zero cross-project code duplication and zero dependency on private employer or SAAT code.

## 2. Reusable Adapter Boundaries

Other projects inside `Trading-Agentic` (such as `financial-agent-evaluation-framework`) can integrate with this agent through stable typed interfaces without importing internal modules:

1. **Python Library Interface (`trading_incident_agent`)**:
   - `TradingIncidentAgent(config=..., advisor=...).investigate(bundle) -> IncidentReport`
   - `TradingIncidentAgent.execute_remediation(report=..., proposal=..., approval=..., environment=...) -> RemediationReceipt`
   - `evaluate_against_oracle(fixtures_dir, config=...) -> dict[str, Any]`
2. **Optional Narrative Advisor Protocol (`trading_incident_agent.llm_adapter.NarrativeAdvisor`)**:
   - Any external LLM SDK or evaluation harness can supply a callable via `CallbackNarrativeAdvisor(fn, config)` while keeping deterministic verdicts, citations, and policy gates completely isolated from model outputs.
3. **CLI JSON Contract (`trading-incident-agent`)**:
   - `investigate --fixture <path> --output-json <path>` emits schema-versioned `IncidentReport` JSON.
   - `evaluate --fixtures-dir <dir> --output-json <path>` emits machine-readable benchmark metrics suitable for external evaluation harnesses.

## 3. Dependency Licenses

| Dependency | Role | Version Constraint | License |
|---|---|---|---|
| Python | Runtime | `>=3.11` (verified on `3.12.15`) | PSF License |
| `pydantic` | Strict input/output data contracts | `>=2.10.0,<3.0.0` (verified on `2.14.4`) | MIT |
| `pytest` (dev) | Unit, integration, and boundary tests | `>=8.3.0,<9.0.0` (verified on `8.4.2`) | MIT |
| `ruff` (dev, optional) | Static linting | `>=0.6.0,<1.0.0` | MIT |

All core logic (`timeline`, `security`, `runbooks`, `hypotheses`, `remediation`, `evaluator`, `cli`) uses Python standard library modules plus Pydantic v2 only, requiring no external network calls or paid APIs.

## 4. Fixture Provenance

All JSON fixtures in `data/fixtures/` are **100% synthetic, hand-authored educational scenarios** created specifically for this prototype:

- Synthetic symbols (`SIMA`, `SIMB`, `SIMC`, `SIMD`) and synthetic venues (`SIMX`, `SIMY`).
- Synthetic order IDs (`ORD-SIM-*`) and placeholder tokens (`sk-synth-FAKE99998888777766665555`, `SYNTH_KEY_DO_NOT_LEAK_12345`) used solely to verify redaction behavior.
- Zero real customer logs, live trading records, production credentials, or proprietary artifacts.
