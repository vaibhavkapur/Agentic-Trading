"""Typed agent adapter protocol and optional disabled-by-default LLM adapter stub."""

from __future__ import annotations

import os
from typing import Protocol

from fin_eval.exceptions import UnsupportedOperationError
from fin_eval.schemas import AgentTrajectory, GoldTask, ModelConfig
from fin_eval.tools.mock_runtime import MockToolRuntime


class FinancialAgentAdapter(Protocol):
    """Protocol implemented by any financial agent evaluated by this framework."""

    agent_id: str

    def run_task(
        self,
        *,
        task: GoldTask,
        runtime: MockToolRuntime,
        config: ModelConfig,
        run_id: str,
        seed: int,
    ) -> AgentTrajectory:
        """Execute a task strictly through the provided sandboxed MockToolRuntime."""
        ...


class OptionalLLMProviderAdapter:
    """Boundary adapter for optional external OpenAI-compatible LLM providers.

    Disabled by default in offline educational/research mode to prevent unintended
    external API calls or credential leakage. Requires explicit opt-in via
    `config.external_network_allowed=True` and runtime environment variables.
    """

    def __init__(self, agent_id: str = "optional-llm-adapter") -> None:
        self.agent_id = agent_id

    def run_task(
        self,
        *,
        task: GoldTask,
        runtime: MockToolRuntime,
        config: ModelConfig,
        run_id: str,
        seed: int,
    ) -> AgentTrajectory:
        if not config.external_network_allowed:
            raise UnsupportedOperationError(
                "External LLM provider calls are disabled by default "
                "(set external_network_allowed=true only for explicitly approved online tests)."
            )
        api_key_env = str(config.agent_options.get("api_key_env", "FIN_EVAL_LLM_API_KEY"))
        if not os.environ.get(api_key_env):
            raise UnsupportedOperationError(
                f"Optional LLM provider requires environment variable '{api_key_env}' to be set; "
                "credentials must never be committed in configs or fixtures."
            )
        raise UnsupportedOperationError(
            "Online LLM provider transport is intentionally excluded from the offline reference "
            "distribution; see docs/integration.md to attach a custom HTTP client adapter."
        )
