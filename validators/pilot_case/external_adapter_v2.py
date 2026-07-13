"""与候选实现分离的 A092 v2 Pilot 外部适配器。"""

from __future__ import annotations

from typing import Any, Mapping


def recompute_objective(
    solution: Mapping[str, float], problem_data: Mapping[str, Any]
) -> float:
    """通过冻结的变量顺序复算目标，避免调用候选评价器。"""

    terms = (
        ("x", float(problem_data["profit"]["x"])),
        ("y", float(problem_data["profit"]["y"])),
    )
    return sum(float(solution[name]) * coefficient for name, coefficient in terms)


def check_constraints(
    solution: Mapping[str, float], problem_data: Mapping[str, Any]
) -> dict[str, float]:
    """返回正值违反量；结果顺序和候选实现无关。"""

    x = float(solution["x"])
    y = float(solution["y"])
    capacity = problem_data["capacity"]
    return {
        "total_capacity": max(0.0, x + y - float(capacity["total"])),
        "machine_hours": max(0.0, 2.0 * x + y - float(capacity["machine_hours"])),
    }
