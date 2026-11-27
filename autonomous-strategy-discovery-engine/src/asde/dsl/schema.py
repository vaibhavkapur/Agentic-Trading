"""Canonical Strategy DSL schema contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union

from asde.types import sha256_canonical


Number = Union[int, float]


@dataclass(frozen=True)
class ParameterSpec:
    """Bounded parameter specification for constrained search."""

    name: str
    param_type: str  # "int" or "float"
    min_value: Number
    max_value: Number
    step: Number

    def grid_values(self) -> List[Number]:
        values: List[Number] = []
        if self.param_type == "int":
            cur = int(self.min_value)
            end = int(self.max_value)
            step = int(self.step)
            while cur <= end:
                values.append(cur)
                cur += step
        else:
            steps = int(round((float(self.max_value) - float(self.min_value)) / float(self.step)))
            for i in range(steps + 1):
                val = round(float(self.min_value) + i * float(self.step), 6)
                if val <= float(self.max_value) + 1e-9:
                    values.append(val)
        return values

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilySpec:
    """Allowed strategy family definition in the catalog."""

    name: str
    description: str
    allow_short: bool
    parameters: Dict[str, ParameterSpec]
    constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "allow_short": self.allow_short,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "constraints": list(self.constraints),
        }


@dataclass(frozen=True)
class StrategyCatalog:
    """Versioned catalog of allowed strategy families, bounds, and baselines."""

    dsl_version: str
    catalog_version: str
    disallowed_constructs: List[str]
    families: Dict[str, FamilySpec]
    baselines: Dict[str, Dict[str, str]]

    def fingerprint(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dsl_version": self.dsl_version,
            "catalog_version": self.catalog_version,
            "disallowed_constructs": list(self.disallowed_constructs),
            "families": {k: v.to_dict() for k, v in self.families.items()},
            "baselines": dict(self.baselines),
        }


@dataclass(frozen=True)
class StrategySpec:
    """Declarative, strictly typed strategy specification in the constrained DSL."""

    strategy_id: str
    family: str
    dsl_version: str
    parameters: Dict[str, Number]
    is_baseline: bool = False
    max_gross_leverage: float = 1.0
    max_single_asset_weight: float = 0.50
    description: str = ""
    raw_code: Optional[str] = None  # Explicitly forbidden if non-None; audited by validator.
    feature_lag_overrides: Dict[str, int] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
