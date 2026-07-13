"""人造产能分配小题的题目适配器。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from validators.common.types import ConstraintValue, VariableSpec


class PilotProductionAdapter:
    """最大化两类产品收益的可复算整数规划小题。"""

    objective_direction = "maximize"
    variable_specs: Sequence[VariableSpec] = (
        VariableSpec("x", 0.0, 10.0, integer=True),
        VariableSpec("y", 0.0, 10.0, integer=False),
    )

    def evaluate_solution(
        self, solution: Mapping[str, float], problem_data: Mapping[str, Any]
    ) -> float:
        return float(problem_data["profit_x"]) * float(solution["x"]) + float(
            problem_data["profit_y"]
        ) * float(solution["y"])

    def evaluate_constraints(
        self, solution: Mapping[str, float], problem_data: Mapping[str, Any]
    ) -> Sequence[ConstraintValue]:
        x = float(solution["x"])
        y = float(solution["y"])
        return (
            ConstraintValue("total_capacity", "inequality", x + y - 10.0, scale=10.0),
            ConstraintValue("machine_hours", "inequality", 2.0 * x + y - 14.0, scale=14.0),
        )

