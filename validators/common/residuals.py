"""变量域与约束残差检查。"""

from __future__ import annotations

from typing import Mapping, Sequence

from .types import ConstraintValue, VariableSpec


def check_variable_bounds(
    solution: Mapping[str, float],
    variable_specs: Sequence[VariableSpec],
    *,
    absolute_tolerance: float,
) -> tuple[bool, list[str]]:
    """按冻结容差检查变量上下界和缺失变量。"""

    violations: list[str] = []
    for spec in variable_specs:
        if spec.name not in solution:
            violations.append(spec.name)
            continue
        value = float(solution[spec.name])
        if value < spec.lower_bound - absolute_tolerance:
            violations.append(spec.name)
        elif value > spec.upper_bound + absolute_tolerance:
            violations.append(spec.name)
    return not violations, violations


def check_integrality(
    solution: Mapping[str, float],
    variable_specs: Sequence[VariableSpec],
    *,
    integrality_tolerance: float,
) -> tuple[bool, list[str]]:
    """检查声明为整数的变量，允许冻结的小量浮点误差。"""

    violations: list[str] = []
    for spec in variable_specs:
        if not spec.integer or spec.name not in solution:
            continue
        value = float(solution[spec.name])
        if abs(value - round(value)) > integrality_tolerance:
            violations.append(spec.name)
    return not violations, violations


def check_constraints(
    values: Sequence[ConstraintValue],
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> tuple[list[dict[str, object]], list[str], float, float]:
    """计算原始/缩放违反量，并按“绝对或相对容差”判定。"""

    results: list[dict[str, object]] = []
    violated: list[str] = []
    max_raw = 0.0
    max_scaled = 0.0
    for constraint in values:
        if constraint.constraint_type == "inequality":
            raw_violation = max(float(constraint.value), 0.0)
        elif constraint.constraint_type == "equality":
            raw_violation = abs(float(constraint.value))
        else:
            raise ValueError(f"未知约束类型: {constraint.constraint_type}")

        scaled_violation = raw_violation / max(abs(float(constraint.scale)), 1.0)
        satisfied = (
            raw_violation <= absolute_tolerance
            or scaled_violation <= relative_tolerance
        )
        if not satisfied:
            violated.append(constraint.constraint_id)
        max_raw = max(max_raw, raw_violation)
        max_scaled = max(max_scaled, scaled_violation)
        results.append(
            {
                "constraint_id": constraint.constraint_id,
                "constraint_type": constraint.constraint_type,
                "raw_residual": raw_violation,
                "scaled_residual": scaled_violation,
                "absolute_tolerance": absolute_tolerance,
                "relative_tolerance": relative_tolerance,
                "satisfied": satisfied,
            }
        )
    return results, violated, max_raw, max_scaled

