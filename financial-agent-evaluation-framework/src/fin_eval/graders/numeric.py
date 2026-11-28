"""Deterministic numeric outcome grader with unit normalization and tolerance checks."""

from __future__ import annotations

import math

from fin_eval.schemas import (
    AgentTrajectory,
    CheckResult,
    FailureType,
    GoldTask,
    NumericUnit,
)

# Conversion factors to canonical base unit within each compatible dimension
_UNIT_DIMENSION_SCALE: dict[NumericUnit, tuple[str, float]] = {
    NumericUnit.USD: ("currency_usd", 1.0),
    NumericUnit.USD_THOUSANDS: ("currency_usd", 1e3),
    NumericUnit.USD_MILLIONS: ("currency_usd", 1e6),
    NumericUnit.USD_BILLIONS: ("currency_usd", 1e9),
    NumericUnit.RATIO: ("rate", 1.0),
    NumericUnit.PERCENT: ("rate", 1e-2),
    NumericUnit.BPS: ("rate", 1e-4),
    NumericUnit.SHARES: ("shares", 1.0),
    NumericUnit.COUNT: ("count", 1.0),
    NumericUnit.DAYS: ("days", 1.0),
}


def convert_unit(value: float, from_unit: NumericUnit, to_unit: NumericUnit) -> float | None:
    """Convert value between compatible financial units; return None if incompatible."""
    if from_unit == to_unit:
        return value
    from_dim, from_scale = _UNIT_DIMENSION_SCALE[from_unit]
    to_dim, to_scale = _UNIT_DIMENSION_SCALE[to_unit]
    if from_dim != to_dim:
        return None
    return value * (from_scale / to_scale)


def grade_numeric(
    task: GoldTask,
    trajectory: AgentTrajectory,
    abstention_warranted: bool = False,
) -> CheckResult:
    """Deterministically verify all expected numeric claims against reference tolerances."""
    if not task.expected_numeric:
        if abstention_warranted and trajectory.abstained and trajectory.numeric_claims:
            return CheckResult(
                check_name="numeric_accuracy",
                passed=False,
                score=0.0,
                failure_types=[FailureType.WRONG_ARITHMETIC],
                details="Agent abstained but still emitted ungrounded numeric claims.",
                diagnostics={"unexpected_claims": len(trajectory.numeric_claims)},
            )
        return CheckResult(
            check_name="numeric_accuracy",
            passed=True,
            score=1.0,
            details="No numeric assertions required for this task.",
        )

    if abstention_warranted and trajectory.abstained:
        if trajectory.numeric_claims:
            return CheckResult(
                check_name="numeric_accuracy",
                passed=False,
                score=0.0,
                failure_types=[FailureType.WRONG_ARITHMETIC],
                details="Agent abstained due to degraded data/tools yet still emitted numeric claims.",
                diagnostics={"emitted_claims": [c.field for c in trajectory.numeric_claims]},
            )
        return CheckResult(
            check_name="numeric_accuracy",
            passed=True,
            score=1.0,
            details="Warranted abstention; numeric output appropriately withheld.",
        )

    claims_by_field = {claim.field: claim for claim in trajectory.numeric_claims}
    failures: list[FailureType] = []
    field_diagnostics: dict[str, dict[str, object]] = {}
    matched = 0

    for exp in task.expected_numeric:
        claim = claims_by_field.get(exp.field)
        if claim is None:
            failures.append(FailureType.WRONG_ARITHMETIC)
            field_diagnostics[exp.field] = {
                "status": "missing",
                "expected": exp.value,
                "expected_unit": exp.unit.value,
            }
            continue

        if math.isnan(claim.value) or math.isinf(claim.value):
            failures.append(FailureType.WRONG_ARITHMETIC)
            field_diagnostics[exp.field] = {
                "status": "non_finite",
                "actual": str(claim.value),
            }
            continue

        converted = convert_unit(claim.value, claim.unit, exp.unit)
        if converted is None:
            failures.append(FailureType.UNIT_MISMATCH)
            field_diagnostics[exp.field] = {
                "status": "unit_mismatch",
                "expected_unit": exp.unit.value,
                "actual_unit": claim.unit.value,
                "actual_value": claim.value,
            }
            continue

        abs_err = abs(converted - exp.value)
        allowed_err = max(exp.abs_tol, exp.rel_tol * abs(exp.value))
        within_tol = abs_err <= allowed_err

        if within_tol:
            matched += 1
            field_diagnostics[exp.field] = {
                "status": "passed",
                "expected": exp.value,
                "actual_normalized": round(converted, 8),
                "unit": exp.unit.value,
                "abs_err": round(abs_err, 8),
                "allowed_err": round(allowed_err, 8),
            }
        else:
            failures.append(FailureType.WRONG_ARITHMETIC)
            field_diagnostics[exp.field] = {
                "status": "out_of_tolerance",
                "expected": exp.value,
                "actual_normalized": round(converted, 8),
                "unit": exp.unit.value,
                "abs_err": round(abs_err, 8),
                "allowed_err": round(allowed_err, 8),
            }

    unique_failures = list(dict.fromkeys(failures))
    score = matched / len(task.expected_numeric)
    passed = len(unique_failures) == 0 and matched == len(task.expected_numeric)

    return CheckResult(
        check_name="numeric_accuracy",
        passed=passed,
        score=round(score, 6),
        failure_types=unique_failures,
        details=f"Matched {matched}/{len(task.expected_numeric)} expected numeric fields.",
        diagnostics={"fields": field_diagnostics},
    )
