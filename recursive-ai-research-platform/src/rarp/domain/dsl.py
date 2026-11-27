"""Declarative Hypothesis and Experiment DSL with strict catalog validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rarp import SCHEMA_VERSION
from rarp.domain.errors import PolicyViolationError, RARPValidationError
from rarp.domain.types import parse_utc_iso, sha256_json


@dataclass(frozen=True)
class ParameterBound:
    name: str
    param_type: str
    min_value: float
    max_value: float

    def validate(self, value: Any) -> float:
        if isinstance(value, bool):
            raise RARPValidationError(
                f"Parameter '{self.name}' cannot be boolean",
                {"parameter": self.name, "value": value},
            )
        if self.param_type == "int":
            if not isinstance(value, int):
                raise RARPValidationError(
                    f"Parameter '{self.name}' must be an integer",
                    {"parameter": self.name, "value": value},
                )
            numeric = int(value)
        elif self.param_type == "float":
            if not isinstance(value, (int, float)):
                raise RARPValidationError(
                    f"Parameter '{self.name}' must be numeric",
                    {"parameter": self.name, "value": value},
                )
            numeric = float(value)
        else:
            raise RARPValidationError(f"Unsupported parameter type: {self.param_type}")

        if numeric < self.min_value or numeric > self.max_value:
            raise RARPValidationError(
                f"Parameter '{self.name}'={numeric} outside allowed bounds [{self.min_value}, {self.max_value}]",
                {
                    "parameter": self.name,
                    "value": numeric,
                    "min": self.min_value,
                    "max": self.max_value,
                },
            )
        return numeric


@dataclass(frozen=True)
class FamilyDefinition:
    name: str
    description: str
    parameters: Dict[str, ParameterBound]
    constraints: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyCatalog:
    schema_version: str
    catalog_version: str
    disallowed_tokens: Tuple[str, ...]
    families: Dict[str, FamilyDefinition]

    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "catalog_version": self.catalog_version,
            "families": {
                fname: {
                    "parameters": {
                        pname: {
                            "type": p.param_type,
                            "min": p.min_value,
                            "max": p.max_value,
                        }
                        for pname, p in sorted(fdef.parameters.items())
                    },
                    "constraints": list(fdef.constraints),
                }
                for fname, fdef in sorted(self.families.items())
            },
        }
        return sha256_json(payload)

    def normalize_parameters(self, family: str, params: Dict[str, Any]) -> Dict[str, float]:
        """Map parameter values to [0, 1] for novelty distance comparison."""
        fdef = self.families[family]
        normalized: Dict[str, float] = {}
        for pname, pbound in sorted(fdef.parameters.items()):
            span = float(pbound.max_value) - float(pbound.min_value)
            val = float(params[pname])
            normalized[pname] = 0.0 if span <= 0 else (val - float(pbound.min_value)) / span
        return normalized


def load_strategy_catalog(path: Path) -> StrategyCatalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    families: Dict[str, FamilyDefinition] = {}
    for fname, fdata in raw["families"].items():
        params = {
            pname: ParameterBound(
                name=pname,
                param_type=pinfo["type"],
                min_value=pinfo["min"],
                max_value=pinfo["max"],
            )
            for pname, pinfo in fdata["parameters"].items()
        }
        families[fname] = FamilyDefinition(
            name=fname,
            description=fdata.get("description", ""),
            parameters=params,
            constraints=tuple(fdata.get("constraints", [])),
        )
    return StrategyCatalog(
        schema_version=raw.get("schema_version", SCHEMA_VERSION),
        catalog_version=raw["catalog_version"],
        disallowed_tokens=tuple(raw.get("disallowed_tokens", [])),
        families=families,
    )


@dataclass(frozen=True)
class CostModelSpec:
    scenario_name: str
    currency: str = "USD"
    commission_bps: float = 1.5
    half_spread_bps: float = 2.0
    slippage_bps: float = 1.5
    annual_borrow_bps: float = 35.0

    def validate(self) -> None:
        if self.currency != "USD":
            raise RARPValidationError("Only USD currency is configured in MVP", {"currency": self.currency})
        for field_name in ("commission_bps", "half_spread_bps", "slippage_bps", "annual_borrow_bps"):
            val = getattr(self, field_name)
            if val < 0:
                raise RARPValidationError(f"Cost parameter '{field_name}' cannot be negative", {field_name: val})

    def one_way_bps(self) -> float:
        return self.commission_bps + self.half_spread_bps + self.slippage_bps

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SplitSpec:
    train_ratio: float = 0.60
    validation_ratio: float = 0.25
    holdout_ratio: float = 0.15
    embargo_bars: int = 5

    def validate(self) -> None:
        total = self.train_ratio + self.validation_ratio + self.holdout_ratio
        if abs(total - 1.0) > 1e-6:
            raise RARPValidationError(
                f"Split ratios must sum to 1.0, got {total:.6f}",
                {"train": self.train_ratio, "validation": self.validation_ratio, "holdout": self.holdout_ratio},
            )
        if self.train_ratio <= 0 or self.validation_ratio <= 0 or self.holdout_ratio <= 0:
            raise RARPValidationError("All split ratios must be strictly positive")
        if self.embargo_bars < 1:
            raise RARPValidationError("embargo_bars must be >= 1 to prevent boundary leakage")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BudgetSpec:
    max_iterations: int = 4
    max_experiments: int = 8
    max_cost_usd: float = 1.00
    cost_per_experiment_usd: float = 0.08
    max_compute_seconds: float = 60.0
    max_llm_tokens: int = 20000

    def validate(self) -> None:
        if self.max_iterations < 1 or self.max_experiments < 1:
            raise RARPValidationError("max_iterations and max_experiments must be >= 1")
        if self.max_cost_usd <= 0 or self.cost_per_experiment_usd < 0:
            raise RARPValidationError("Budget cost limits must be positive")
        if self.max_compute_seconds <= 0 or self.max_llm_tokens < 0:
            raise RARPValidationError("Compute and token limits must be valid non-negative numbers")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StopConditionsSpec:
    max_consecutive_failures: int = 3
    min_improvement_sharpe: float = 0.02
    patience_rounds: int = 2
    near_duplicate_distance: float = 0.03

    def validate(self) -> None:
        if self.max_consecutive_failures < 1:
            raise RARPValidationError("max_consecutive_failures must be >= 1")
        if self.patience_rounds < 1:
            raise RARPValidationError("patience_rounds must be >= 1")
        if self.near_duplicate_distance < 0:
            raise RARPValidationError("near_duplicate_distance must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataManifest:
    manifest_id: str
    dataset_name: str
    schema_version: str
    source_type: str
    entitlement: str
    license_notes: str
    symbols: Tuple[str, ...]
    row_count: int
    start_event_time_utc: str
    end_event_time_utc: str
    content_sha256: str
    created_at_utc: str
    file_path: str

    def validate(self) -> None:
        if not self.manifest_id or not self.content_sha256:
            raise RARPValidationError("DataManifest requires manifest_id and content_sha256")
        start = parse_utc_iso(self.start_event_time_utc)
        end = parse_utc_iso(self.end_event_time_utc)
        if start >= end:
            raise RARPValidationError("DataManifest start_event_time_utc must precede end_event_time_utc")
        parse_utc_iso(self.created_at_utc)
        if self.row_count <= 0:
            raise RARPValidationError("DataManifest row_count must be > 0")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["symbols"] = list(self.symbols)
        return data

    def manifest_sha256(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataManifest":
        return cls(
            manifest_id=data["manifest_id"],
            dataset_name=data["dataset_name"],
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            source_type=data["source_type"],
            entitlement=data["entitlement"],
            license_notes=data["license_notes"],
            symbols=tuple(data["symbols"]),
            row_count=int(data["row_count"]),
            start_event_time_utc=data["start_event_time_utc"],
            end_event_time_utc=data["end_event_time_utc"],
            content_sha256=data["content_sha256"],
            created_at_utc=data["created_at_utc"],
            file_path=data["file_path"],
        )


@dataclass(frozen=True)
class HypothesisSpec:
    hypothesis_id: str
    title: str
    rationale: str
    family: str
    parameters: Dict[str, Any]
    universe: Tuple[str, ...]
    proposer_id: str
    created_at_utc: str
    parent_hypothesis_id: Optional[str] = None
    generation: int = 0
    tags: Tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def validate(self, catalog: StrategyCatalog) -> None:
        if not self.hypothesis_id or not self.proposer_id:
            raise RARPValidationError("hypothesis_id and proposer_id are required")
        parse_utc_iso(self.created_at_utc)
        if not self.universe:
            raise RARPValidationError("Hypothesis universe cannot be empty")
        if self.generation < 0:
            raise RARPValidationError("Hypothesis generation must be >= 0")

        # Ban unrestricted generated code in any string field or parameter key/value.
        serialized = json.dumps(self.to_dict(), sort_keys=True)
        for token in catalog.disallowed_tokens:
            if token in serialized:
                raise PolicyViolationError(
                    f"Unrestricted code token '{token}' is explicitly prohibited in HypothesisSpec",
                    {"hypothesis_id": self.hypothesis_id, "token": token},
                )
        for forbidden_key in ("code", "script", "python_expr", "custom_fn"):
            if forbidden_key in self.parameters:
                raise PolicyViolationError(
                    f"Arbitrary code parameter '{forbidden_key}' is prohibited",
                    {"hypothesis_id": self.hypothesis_id, "parameter": forbidden_key},
                )

        if self.family not in catalog.families:
            raise RARPValidationError(
                f"Unknown strategy family '{self.family}'. Allowed: {sorted(catalog.families)}",
                {"family": self.family},
            )
        fdef = catalog.families[self.family]

        expected_keys = set(fdef.parameters.keys())
        actual_keys = set(self.parameters.keys())
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        if missing or extra:
            raise RARPValidationError(
                f"Parameter schema mismatch for family '{self.family}'",
                {"missing": missing, "extra": extra},
            )

        for pname, pbound in fdef.parameters.items():
            pbound.validate(self.parameters[pname])

        # Strictly require causal lag >= 1 bar to prevent lookahead bias.
        lag = int(self.parameters.get("signal_lag_bars", 0))
        if lag < 1:
            raise RARPValidationError("signal_lag_bars must be >= 1 to guarantee causal execution")

        # Family-specific relational constraints.
        for constraint in fdef.constraints:
            if constraint == "fast_window < slow_window":
                if self.parameters["fast_window"] >= self.parameters["slow_window"]:
                    raise RARPValidationError(
                        "Constraint violated: fast_window must be strictly less than slow_window",
                        {"fast_window": self.parameters["fast_window"], "slow_window": self.parameters["slow_window"]},
                    )
            elif constraint == "exit_z < entry_z":
                if self.parameters["exit_z"] >= self.parameters["entry_z"]:
                    raise RARPValidationError(
                        "Constraint violated: exit_z must be strictly less than entry_z",
                        {"exit_z": self.parameters["exit_z"], "entry_z": self.parameters["entry_z"]},
                    )

    def semantic_fingerprint(self) -> str:
        """Canonical SHA-256 fingerprint independent of hypothesis_id/timestamp for duplicate detection."""
        normalized_params = {
            k: round(float(v), 8) if isinstance(v, float) else int(v)
            for k, v in sorted(self.parameters.items())
        }
        payload = {
            "family": self.family,
            "parameters": normalized_params,
            "universe": sorted(self.universe),
        }
        return sha256_json(payload)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "title": self.title,
            "rationale": self.rationale,
            "family": self.family,
            "parameters": dict(sorted(self.parameters.items())),
            "universe": list(self.universe),
            "proposer_id": self.proposer_id,
            "created_at_utc": self.created_at_utc,
            "parent_hypothesis_id": self.parent_hypothesis_id,
            "generation": self.generation,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HypothesisSpec":
        return cls(
            hypothesis_id=data["hypothesis_id"],
            title=data["title"],
            rationale=data["rationale"],
            family=data["family"],
            parameters=dict(data["parameters"]),
            universe=tuple(data["universe"]),
            proposer_id=data["proposer_id"],
            created_at_utc=data["created_at_utc"],
            parent_hypothesis_id=data.get("parent_hypothesis_id"),
            generation=int(data.get("generation", 0)),
            tags=tuple(data.get("tags", ())),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    hypothesis: HypothesisSpec
    data_manifest_id: str
    data_manifest_sha256: str
    split: SplitSpec
    cost_model: CostModelSpec
    seed: int
    initial_capital_usd: float = 1_000_000.0
    code_version: str = "0.1.0"
    schema_version: str = SCHEMA_VERSION
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self, catalog: StrategyCatalog) -> None:
        if not self.experiment_id:
            raise RARPValidationError("experiment_id is required")
        if self.initial_capital_usd <= 0:
            raise RARPValidationError("initial_capital_usd must be > 0")
        self.hypothesis.validate(catalog)
        self.split.validate()
        self.cost_model.validate()

    def idempotency_key(self) -> str:
        payload = {
            "hypothesis_fingerprint": self.hypothesis.semantic_fingerprint(),
            "data_manifest_id": self.data_manifest_id,
            "data_manifest_sha256": self.data_manifest_sha256,
            "split": self.split.to_dict(),
            "cost_model": self.cost_model.to_dict(),
            "seed": self.seed,
            "initial_capital_usd": self.initial_capital_usd,
            "code_version": self.code_version,
        }
        return sha256_json(payload)

    def config_sha256(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis.to_dict(),
            "data_manifest_id": self.data_manifest_id,
            "data_manifest_sha256": self.data_manifest_sha256,
            "split": self.split.to_dict(),
            "cost_model": self.cost_model.to_dict(),
            "seed": self.seed,
            "initial_capital_usd": self.initial_capital_usd,
            "code_version": self.code_version,
            "metadata": dict(sorted(self.metadata.items())),
        }
