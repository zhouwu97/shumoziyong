"""Validator v0 的题目适配器合同。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class VariableSpec:
    """单个决策变量的定义。"""

    name: str
    lower_bound: float
    upper_bound: float
    integer: bool = False


@dataclass(frozen=True)
class ConstraintValue:
    """已统一为 ``g(x) <= 0`` 或 ``h(x) = 0`` 的约束值。"""

    constraint_id: str
    constraint_type: str
    value: float
    scale: float = 1.0


class ProblemAdapter(Protocol):
    """每道题必须实现的最小数学接口。"""

    objective_direction: str
    variable_specs: Sequence[VariableSpec]

    def evaluate_solution(
        self, solution: Mapping[str, float], problem_data: Mapping[str, Any]
    ) -> float:
        """使用固定评价器独立计算目标值。"""

        ...

    def evaluate_constraints(
        self, solution: Mapping[str, float], problem_data: Mapping[str, Any]
    ) -> Sequence[ConstraintValue]:
        """返回标准化前的约束函数值。"""

        ...
