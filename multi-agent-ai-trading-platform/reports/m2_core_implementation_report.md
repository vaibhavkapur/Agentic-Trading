# Milestone M2 Report — Core Implementation

## Scope Delivered
- Implemented `BoundedToolGateway` (`src/trading_platform/tools/gateway.py`) enforcing allowlisted read-only tools, per-agent (`max_tool_calls_per_agent=6`) and per-run (`max_total_tool_calls=16`) call budgets, malicious argument scanning (SQLi, path traversal, shell metacharacters, control chars), and automatic `EvidenceItem` provenance hashing.
- Implemented `PromptInjectionGuard` (`src/trading_platform/agents/base.py`) to detect, redact, quarantine, and audit adversarial instructions embedded in untrusted news feeds.
- Implemented read-only research adapters (`FundamentalResearchAgent`, `MomentumNewsResearchAgent`) and read-only `PortfolioAgentAdapter` producing typed `ResearchReport` and `PortfolioProposal` artifacts linked to `evidence_ids` and `policy_version`.
- Implemented bounded `MultiAgentOrchestrator` (`src/trading_platform/orchestrator/engine.py`) coordinating research, directional conflict detection, portfolio proposal synthesis, independent risk evaluation, policy gating, and approval request creation.

## Verification Evidence
- Unit tests: `tests/unit/test_tool_gateway_and_permissions.py` (3 passed).
- Scenario tests: `test_scenario_1_injected_instructions_in_news`, `test_scenario_2_malicious_tool_arguments`, `test_scenario_4_conflicting_agents` (all passed).
- Raw pytest log: [evidence/pytest_output.txt](evidence/pytest_output.txt).
