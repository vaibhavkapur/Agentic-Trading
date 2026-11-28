"""Configuration loading, digest computation, and runtime metadata capture."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from trading_incident_agent.errors import ConfigurationError, InputValidationError, UnsupportedSchemaError
from trading_incident_agent.models import (
    SUPPORTED_SCHEMA_VERSION,
    AgentConfig,
    IncidentBundle,
    RuntimeMetadata,
)

PACKAGE_VERSION = "0.1.0"


def canonical_json(data: Any) -> str:
    """Serialize data deterministically for hashing and reproducible outputs."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_sha256(data: Any) -> str:
    """Compute a deterministic SHA-256 hex digest over canonical JSON."""
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> AgentConfig:
    """Load and validate an AgentConfig JSON file."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigurationError(
            f"Configuration file not found: {cfg_path}",
            details={"path": str(cfg_path)},
        )
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Malformed JSON in configuration file {cfg_path}: {exc}",
            details={"path": str(cfg_path)},
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"Configuration root must be a JSON object in {cfg_path}",
            details={"path": str(cfg_path)},
        )
    try:
        return AgentConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Invalid configuration schema in {cfg_path}: {exc}",
            details={"path": str(cfg_path), "errors": exc.errors()},
        ) from exc


def load_incident_bundle(path: str | Path) -> IncidentBundle:
    """Load and strictly validate a versioned IncidentBundle JSON file."""
    bundle_path = Path(path)
    if not bundle_path.exists():
        raise InputValidationError(
            f"Incident fixture file not found: {bundle_path}",
            details={"path": str(bundle_path)},
        )
    try:
        raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            f"Malformed JSON in incident fixture {bundle_path}: {exc}",
            details={"path": str(bundle_path)},
        ) from exc
    return validate_incident_bundle(raw)


def validate_incident_bundle(raw: dict[str, Any] | IncidentBundle) -> IncidentBundle:
    """Validate raw dict or IncidentBundle against schema version and environment rules."""
    if isinstance(raw, IncidentBundle):
        bundle = raw
    else:
        if not isinstance(raw, dict):
            raise InputValidationError("Incident input must be a JSON object")
        schema_version = raw.get("schema_version", SUPPORTED_SCHEMA_VERSION)
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise UnsupportedSchemaError(
                f"Unsupported schema_version '{schema_version}'; expected '{SUPPORTED_SCHEMA_VERSION}'",
                details={"schema_version": schema_version, "supported": SUPPORTED_SCHEMA_VERSION},
            )
        env = raw.get("environment", "synthetic")
        if env not in {"synthetic", "paper", "sim"}:
            raise UnsupportedSchemaError(
                f"Unsupported environment '{env}'; only 'synthetic', 'paper', or 'sim' are permitted",
                details={"environment": env},
            )
        try:
            bundle = IncidentBundle.model_validate(raw)
        except ValidationError as exc:
            raise InputValidationError(
                f"Incident bundle validation failed: {exc}",
                details={"errors": exc.errors()},
            ) from exc

    if bundle.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"Unsupported schema_version '{bundle.schema_version}'; expected '{SUPPORTED_SCHEMA_VERSION}'",
            details={"schema_version": bundle.schema_version},
        )
    return bundle


def build_runtime_metadata(config: AgentConfig, bundle: IncidentBundle) -> RuntimeMetadata:
    """Capture deterministic config/input digests and runtime environment details."""
    config_digest = compute_sha256(config.model_dump(mode="json"))
    input_digest = compute_sha256(bundle.model_dump(mode="json"))
    return RuntimeMetadata(
        package_version=PACKAGE_VERSION,
        schema_version=bundle.schema_version,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        config_digest=config_digest,
        input_digest=input_digest,
        seed=config.seed,
        advisor_mode=config.advisor_mode,
    )
