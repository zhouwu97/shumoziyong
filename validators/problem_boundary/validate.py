"""2023-B 问题一、二的解析公式适配器。"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


DISTANCES_Q1 = (-800, -600, -400, -200, 0, 200, 400, 600, 800)
DISTANCES_Q2_NM = (0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1)
BETAS_DEG = (0, 45, 90, 135, 180, 225, 270, 315)


def coverage_width(depth: float, slope_deg: float, opening_deg: float, beta_deg: float = 90.0) -> float:
    """按局部横坡角计算多波束条带宽度。"""

    half = math.radians(opening_deg / 2.0)
    effective_slope = math.atan(
        math.tan(math.radians(slope_deg)) * math.sin(math.radians(beta_deg))
    )
    left = depth * math.sin(half) / math.cos(half + effective_slope)
    right = depth * math.sin(half) / math.cos(half - effective_slope)
    return left + right


def expected_tables() -> dict[str, Any]:
    slope = 1.5
    opening = 120.0
    q1_depths = [70.0 - distance * math.tan(math.radians(slope)) for distance in DISTANCES_Q1]
    q1_widths = [coverage_width(depth, slope, opening) for depth in q1_depths]
    overlaps: list[float | None] = [None]
    for index in range(1, len(DISTANCES_Q1)):
        spacing = DISTANCES_Q1[index] - DISTANCES_Q1[index - 1]
        overlaps.append(1.0 - spacing / q1_widths[index])

    q2: list[dict[str, Any]] = []
    for beta in BETAS_DEG:
        row = []
        for distance_nm in DISTANCES_Q2_NM:
            depth = 120.0 - distance_nm * 1852.0 * math.tan(math.radians(slope))
            row.append(coverage_width(depth, slope, opening, beta))
        q2.append({"beta_deg": beta, "coverage_width_m": row})
    return {
        "q1": {
            "distances_m": list(DISTANCES_Q1),
            "depth_m": q1_depths,
            "coverage_width_m": q1_widths,
            "overlap_ratio": overlaps,
        },
        "q2": {"distances_nm": list(DISTANCES_Q2_NM), "rows": q2},
    }


def _max_difference(actual: Sequence[float], expected: Sequence[float]) -> float:
    if len(actual) != len(expected):
        return math.inf
    return max((abs(float(a) - float(e)) for a, e in zip(actual, expected)), default=0.0)


def validate_result(result: Mapping[str, Any], tolerance: float = 1e-6) -> dict[str, Any]:
    """独立复算两张表并核验模型输出。"""

    expected = expected_tables()
    q1 = result.get("q1", {})
    q2 = result.get("q2", {})
    differences = [
        _max_difference(q1.get("depth_m", []), expected["q1"]["depth_m"]),
        _max_difference(q1.get("coverage_width_m", []), expected["q1"]["coverage_width_m"]),
    ]
    actual_overlaps = q1.get("overlap_ratio", [])
    if len(actual_overlaps) != len(expected["q1"]["overlap_ratio"]):
        differences.append(math.inf)
    else:
        differences.extend(
            abs(float(actual) - float(reference))
            for actual, reference in zip(actual_overlaps[1:], expected["q1"]["overlap_ratio"][1:])
        )
    actual_rows = {int(row["beta_deg"]): row["coverage_width_m"] for row in q2.get("rows", [])}
    for expected_row in expected["q2"]["rows"]:
        differences.append(
            _max_difference(
                actual_rows.get(int(expected_row["beta_deg"]), []),
                expected_row["coverage_width_m"],
            )
        )
    maximum = max(differences, default=math.inf)
    return {
        "validator": "a092_2023b_q1_q2_v1",
        "max_absolute_difference": maximum,
        "tolerance": tolerance,
        "objective_applicable": False,
        "constraints_applicable": False,
        "sensitivity_applicable": False,
        "valid": math.isfinite(maximum) and maximum <= tolerance,
        "expected": expected,
    }

