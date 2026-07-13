"""A092 v2 Pilot 的候选侧评价器。"""

from __future__ import annotations

from typing import Any, Mapping


def evaluate_solution(
    solution: Mapping[str, float], problem_data: Mapping[str, Any]
) -> float:
    """模拟候选生成过程内部的直接目标计算。"""

    return float(problem_data["profit"]["x"]) * float(solution["x"]) + float(
        problem_data["profit"]["y"]
    ) * float(solution["y"])
