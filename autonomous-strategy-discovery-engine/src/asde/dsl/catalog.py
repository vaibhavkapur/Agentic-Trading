"""Strategy catalog loader and strict DSL validator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from asde.dsl.schema import FamilySpec, ParameterSpec, StrategyCatalog, StrategySpec
from asde.errors import DslValidationError, LookAheadError, UnconstrainedCodeError


_FORBIDDEN_CODE_KEYS = {"code", "python", "eval", "exec", "lambda", "expression", "script"}


def load_catalog(path: Path) -> StrategyCatalog:
    """Load and parse a versioned strategy catalog JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    families: Dict[str, FamilySpec] = {}
    for fname, fdata in raw["families"].items():
        params: Dict[str, ParameterSpec] = {}
        for pname, pdata in fdata["parameters"].items():
            params[pname] = ParameterSpec(
                name=pname,
                param_type=pdata["type"],
                min_value=pdata["min"],
                max_value=pdata["max"],
                step=pdata["step"],
            )
        families[fname] = FamilySpec(
            name=fname,
            description=fdata["description"],
            allow_short=bool(fdata["allow_short"]),
            parameters=params,
            constraints=list(fdata.get("constraints", [])),
        )
    return StrategyCatalog(
        dsl_version=raw["dsl_version"],
        catalog_version=raw["catalog_version"],
        disallowed_constructs=list(raw.get("disallowed_constructs", [])),
        families=families,
        baselines=dict(raw.get("baselines", {})),
    )


def build_baseline_spec(baseline_name: str, catalog: StrategyCatalog) -> StrategySpec:
    """Create a validated baseline strategy spec from the catalog."""
    if baseline_name not in catalog.baselines:
        raise DslValidationError(
            f"Unknown baseline {baseline_name!r}",
            details={"allowed_baselines": sorted(catalog.baselines.keys())},
        )
    return StrategySpec(
        strategy_id=baseline_name,
        family=baseline_name,
        dsl_version=catalog.dsl_version,
        parameters={"signal_lag_bars": 1},
        is_baseline=True,
        max_gross_leverage=1.0,
        max_single_asset_weight=1.0,
        description=catalog.baselines[baseline_name].get("description", ""),
    )


def validate_strategy_spec(spec: StrategySpec, catalog: StrategyCatalog) -> None:
    """Strictly validate a StrategySpec against the catalog and safety invariants.

    Enforces:
    - No unconstrained code generation (raw_code or code-like keys forbidden)
    - Matching DSL version
    - Allowed strategy family or baseline
    - Parameter bounds, types, and cross-parameter constraints
    - Non-look-ahead lag invariants (>= 1 bar lag, no negative lag overrides)
    - Leverage and concentration bounds
    """
    if spec.raw_code is not None:
        raise UnconstrainedCodeError(
            "Unconstrained code generation is explicitly forbidden in the strategy DSL.",
            details={"strategy_id": spec.strategy_id},
        )

    for key in spec.parameters.keys():
        if key.lower() in _FORBIDDEN_CODE_KEYS:
            raise UnconstrainedCodeError(
                f"Forbidden unconstrained code parameter {key!r} in strategy {spec.strategy_id!r}.",
                details={"strategy_id": spec.strategy_id, "parameter": key},
            )

    for feat, lag in spec.feature_lag_overrides.items():
        if lag < 1:
            raise LookAheadError(
                f"Look-ahead violation: feature {feat!r} has lag {lag} < 1.",
                details={"strategy_id": spec.strategy_id, "feature": feat, "lag": lag},
            )

    if spec.dsl_version != catalog.dsl_version:
        raise DslValidationError(
            f"DSL version mismatch: got {spec.dsl_version!r}, expected {catalog.dsl_version!r}.",
            details={"strategy_id": spec.strategy_id},
        )

    if spec.max_gross_leverage <= 0.0 or spec.max_gross_leverage > 2.0:
        raise DslValidationError(
            f"max_gross_leverage must be in (0, 2.0], got {spec.max_gross_leverage}",
            details={"strategy_id": spec.strategy_id},
        )

    if spec.max_single_asset_weight <= 0.0 or spec.max_single_asset_weight > 1.0:
        raise DslValidationError(
            f"max_single_asset_weight must be in (0, 1.0], got {spec.max_single_asset_weight}",
            details={"strategy_id": spec.strategy_id},
        )

    if spec.is_baseline:
        if spec.family not in catalog.baselines:
            raise DslValidationError(
                f"Unknown baseline family {spec.family!r}.",
                details={"allowed_baselines": sorted(catalog.baselines.keys())},
            )
        lag = int(spec.parameters.get("signal_lag_bars", 1))
        if lag < 1:
            raise LookAheadError(
                f"Baseline signal_lag_bars must be >= 1, got {lag}.",
                details={"strategy_id": spec.strategy_id, "signal_lag_bars": lag},
            )
        return

    if spec.family not in catalog.families:
        raise DslValidationError(
            f"Strategy family {spec.family!r} is not in the allowed catalog.",
            details={"strategy_id": spec.strategy_id, "allowed_families": sorted(catalog.families.keys())},
        )

    family = catalog.families[spec.family]
    missing = set(family.parameters.keys()) - set(spec.parameters.keys())
    extra = set(spec.parameters.keys()) - set(family.parameters.keys())
    if missing or extra:
        raise DslValidationError(
            f"Parameter mismatch for family {spec.family!r}.",
            details={"missing": sorted(missing), "extra": sorted(extra)},
        )

    for pname, pspec in family.parameters.items():
        val = spec.parameters[pname]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise DslValidationError(
                f"Parameter {pname!r} must be numeric, got {type(val).__name__}.",
                details={"strategy_id": spec.strategy_id, "parameter": pname},
            )
        if pspec.param_type == "int" and not isinstance(val, int):
            raise DslValidationError(
                f"Parameter {pname!r} must be an integer, got {val!r}.",
                details={"strategy_id": spec.strategy_id, "parameter": pname},
            )
        if pname == "signal_lag_bars" and val < 1:
            raise LookAheadError(
                f"Look-ahead violation: signal_lag_bars={val} < 1.",
                details={"strategy_id": spec.strategy_id, "signal_lag_bars": val},
            )
        if val < pspec.min_value - 1e-9 or val > pspec.max_value + 1e-9:
            raise DslValidationError(
                f"Parameter {pname!r}={val} out of bounds [{pspec.min_value}, {pspec.max_value}].",
                details={"strategy_id": spec.strategy_id, "parameter": pname, "value": val},
            )

    for constraint in family.constraints:
        _check_constraint(constraint, spec)


def _check_constraint(constraint: str, spec: StrategySpec) -> None:
    """Evaluate safe declarative binary inequality constraints without eval()."""
    parts = constraint.split()
    if len(parts) != 3:
        raise DslValidationError(f"Unsupported constraint format: {constraint!r}")
    lhs_name, op, rhs_name = parts
    lhs = float(spec.parameters[lhs_name])
    rhs = float(spec.parameters[rhs_name])
    ok = False
    if op == "<":
        ok = lhs < rhs
    elif op == "<=":
        ok = lhs <= rhs
    elif op == ">":
        ok = lhs > rhs
    elif op == ">=":
        ok = lhs >= rhs
    else:
        raise DslValidationError(f"Unsupported constraint operator: {op!r}")
    if not ok:
        raise DslValidationError(
            f"Constraint {constraint!r} violated for {spec.strategy_id!r} ({lhs_name}={lhs}, {rhs_name}={rhs}).",
            details={"strategy_id": spec.strategy_id, "constraint": constraint},
        )
