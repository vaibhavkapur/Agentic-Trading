"""Configuration loading and safety-boundary validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .errors import ConfigurationError
from .models import canonical_json, parse_decimal, sha256_text


@dataclass(frozen=True)
class ModelAdapterConfig:
    provider: str = "deterministic_mock"
    max_calls_per_run: int = 4
    max_output_tokens: int = 1200
    allow_live_network: bool = False

    def __post_init__(self) -> None:
        if self.provider not in ("deterministic_mock", "none"):
            raise ConfigurationError(
                f"Unsupported model_adapter.provider: '{self.provider}'. "
                "Only offline 'deterministic_mock' or 'none' are permitted in this prototype.",
                details={"provider": self.provider},
            )
        if self.max_calls_per_run < 0:
            raise ConfigurationError(
                "model_adapter.max_calls_per_run must be >= 0",
                details={"max_calls_per_run": self.max_calls_per_run},
            )
        if self.max_output_tokens < 64:
            raise ConfigurationError(
                "model_adapter.max_output_tokens must be >= 64",
                details={"max_output_tokens": self.max_output_tokens},
            )
        if self.allow_live_network:
            raise ConfigurationError(
                "model_adapter.allow_live_network=true is prohibited in offline research mode",
                details={"allow_live_network": True},
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "max_calls_per_run": self.max_calls_per_run,
            "max_output_tokens": self.max_output_tokens,
            "allow_live_network": self.allow_live_network,
        }


@dataclass(frozen=True)
class BriefPolicyConfig:
    require_citation_for_all_figures: bool = True
    abstain_on_unresolved_conflict: bool = True
    abstain_on_unit_mismatch: bool = True
    abstain_on_missing_consensus_for_surprise: bool = True
    frame_as_hypotheses_only: bool = True

    def __post_init__(self) -> None:
        if not self.require_citation_for_all_figures:
            raise ConfigurationError(
                "brief_policy.require_citation_for_all_figures cannot be disabled"
            )
        if not self.frame_as_hypotheses_only:
            raise ConfigurationError(
                "brief_policy.frame_as_hypotheses_only must remain true (predictions are out of scope)"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "require_citation_for_all_figures": self.require_citation_for_all_figures,
            "abstain_on_unresolved_conflict": self.abstain_on_unresolved_conflict,
            "abstain_on_unit_mismatch": self.abstain_on_unit_mismatch,
            "abstain_on_missing_consensus_for_surprise": self.abstain_on_missing_consensus_for_surprise,
            "frame_as_hypotheses_only": self.frame_as_hypotheses_only,
        }


@dataclass(frozen=True)
class StorageConfig:
    default_db_path: str = ":memory:"
    enable_run_replay_log: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_db_path": self.default_db_path,
            "enable_run_replay_log": self.enable_run_replay_log,
        }


@dataclass(frozen=True)
class AgentConfig:
    config_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    seed: int = 42
    numeric_tolerance: Decimal = Decimal("0.0001")
    conflict_tolerance_ratio: Decimal = Decimal("0.001")
    enable_unit_auto_conversion: bool = True
    strict_untrusted_instruction_mode: str = "quarantine"  # "quarantine" | "reject"
    model_adapter: ModelAdapterConfig = field(default_factory=ModelAdapterConfig)
    brief_policy: BriefPolicyConfig = field(default_factory=BriefPolicyConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def __post_init__(self) -> None:
        if self.strict_untrusted_instruction_mode not in ("quarantine", "reject"):
            raise ConfigurationError(
                f"Invalid strict_untrusted_instruction_mode: '{self.strict_untrusted_instruction_mode}'",
                details={"allowed": ["quarantine", "reject"]},
            )
        if self.numeric_tolerance < Decimal("0"):
            raise ConfigurationError("numeric_tolerance must be >= 0")
        if self.conflict_tolerance_ratio < Decimal("0"):
            raise ConfigurationError("conflict_tolerance_ratio must be >= 0")

    @property
    def config_sha256(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_version": self.config_version,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "numeric_tolerance": format(self.numeric_tolerance, "f"),
            "conflict_tolerance_ratio": format(self.conflict_tolerance_ratio, "f"),
            "enable_unit_auto_conversion": self.enable_unit_auto_conversion,
            "strict_untrusted_instruction_mode": self.strict_untrusted_instruction_mode,
            "model_adapter": self.model_adapter.to_dict(),
            "brief_policy": self.brief_policy.to_dict(),
            "storage": self.storage.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        if not isinstance(data, dict):
            raise ConfigurationError("Config root must be a JSON object")
        ma_raw = data.get("model_adapter", {})
        bp_raw = data.get("brief_policy", {})
        st_raw = data.get("storage", {})
        if not isinstance(ma_raw, dict) or not isinstance(bp_raw, dict) or not isinstance(st_raw, dict):
            raise ConfigurationError("model_adapter, brief_policy, and storage must be objects")
        try:
            seed = int(data.get("seed", 42))
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("seed must be an integer") from exc
        return cls(
            config_version=str(data.get("config_version", "1.0.0")),
            schema_version=str(data.get("schema_version", "1.0.0")),
            seed=seed,
            numeric_tolerance=parse_decimal(
                data.get("numeric_tolerance", "0.0001"), "numeric_tolerance"
            ),
            conflict_tolerance_ratio=parse_decimal(
                data.get("conflict_tolerance_ratio", "0.001"), "conflict_tolerance_ratio"
            ),
            enable_unit_auto_conversion=bool(data.get("enable_unit_auto_conversion", True)),
            strict_untrusted_instruction_mode=str(
                data.get("strict_untrusted_instruction_mode", "quarantine")
            ),
            model_adapter=ModelAdapterConfig(
                provider=str(ma_raw.get("provider", "deterministic_mock")),
                max_calls_per_run=int(ma_raw.get("max_calls_per_run", 4)),
                max_output_tokens=int(ma_raw.get("max_output_tokens", 1200)),
                allow_live_network=bool(ma_raw.get("allow_live_network", False)),
            ),
            brief_policy=BriefPolicyConfig(
                require_citation_for_all_figures=bool(
                    bp_raw.get("require_citation_for_all_figures", True)
                ),
                abstain_on_unresolved_conflict=bool(
                    bp_raw.get("abstain_on_unresolved_conflict", True)
                ),
                abstain_on_unit_mismatch=bool(bp_raw.get("abstain_on_unit_mismatch", True)),
                abstain_on_missing_consensus_for_surprise=bool(
                    bp_raw.get("abstain_on_missing_consensus_for_surprise", True)
                ),
                frame_as_hypotheses_only=bool(bp_raw.get("frame_as_hypotheses_only", True)),
            ),
            storage=StorageConfig(
                default_db_path=str(st_raw.get("default_db_path", ":memory:")),
                enable_run_replay_log=bool(st_raw.get("enable_run_replay_log", True)),
            ),
        )


def load_config(path: Optional[Union[str, Path]] = None) -> AgentConfig:
    """Load configuration from JSON file; raise ConfigurationError if missing or invalid."""
    if path is None:
        return AgentConfig()
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigurationError(
            f"Configuration file not found: {cfg_path}",
            details={"path": str(cfg_path)},
        )
    try:
        raw_text = cfg_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Failed to read or parse configuration file {cfg_path}: {exc}",
            details={"path": str(cfg_path)},
        ) from exc
    return AgentConfig.from_dict(data)
