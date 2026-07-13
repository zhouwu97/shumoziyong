"""冻结的基线改进率口径。"""

from __future__ import annotations


def compare_with_baseline(
    *,
    objective_direction: str,
    baseline_objective: float,
    candidate_objective: float,
    epsilon: float,
    reported_ratio: float | None = None,
    ratio_tolerance: float = 1e-9,
) -> dict[str, float | bool | None]:
    """计算绝对改进和以 ``abs(baseline)`` 为分母的相对改进。"""

    if objective_direction == "maximize":
        improvement = candidate_objective - baseline_objective
    elif objective_direction == "minimize":
        improvement = baseline_objective - candidate_objective
    else:
        raise ValueError(f"未知目标方向: {objective_direction}")

    baseline_near_zero = abs(baseline_objective) <= epsilon
    ratio = None if baseline_near_zero else improvement / abs(baseline_objective)
    if reported_ratio is None:
        ratio_consistent = True
    elif ratio is None:
        ratio_consistent = False
    else:
        ratio_consistent = abs(reported_ratio - ratio) <= ratio_tolerance
    return {
        "absolute_improvement": improvement,
        "improvement_ratio": ratio,
        "baseline_near_zero": baseline_near_zero,
        "improvement_ratio_consistent": ratio_consistent,
    }

