"""2023-B 问题一、二经题面图示复核后的解析适配器。"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


DISTANCES_Q1 = (-800, -600, -400, -200, 0, 200, 400, 600, 800)
DISTANCES_Q2_NM = (0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1)
BETAS_DEG = (0, 45, 90, 135, 180, 225, 270, 315)
SLOPE_DEG = 1.5
OPENING_DEG = 120.0
NAUTICAL_MILE_M = 1852.0


def coverage_halves(
    depth: float,
    opening_deg: float,
    cross_slope_rad: float,
) -> tuple[float, float]:
    """返回沿海底交线计的深水侧、浅水侧半宽。"""
    if depth <= 0:
        raise ValueError(f"水深必须为正，实际为 {depth}")
    half = math.radians(opening_deg / 2.0)
    if abs(cross_slope_rad) + half >= math.pi / 2.0:
        raise ValueError("边缘波束与坡面不形成有限有效交点")
    deep = depth * math.sin(half) / math.cos(half + cross_slope_rad)
    shallow = depth * math.sin(half) / math.cos(half - cross_slope_rad)
    return deep, shallow


def coverage_width(
    depth: float,
    slope_deg: float,
    opening_deg: float,
    beta_deg: float = 90.0,
) -> float:
    """按测线横向截面内的有效坡度计算覆盖宽度。"""
    beta = math.radians(beta_deg)
    effective_slope = math.atan(math.tan(math.radians(slope_deg)) * math.sin(beta))
    return sum(coverage_halves(depth, opening_deg, effective_slope))


def q2_depth(distance_nm: float, beta_deg: float) -> float:
    """计算沿测线离开中心后的水深；beta=0 为深水方向。"""
    distance_m = distance_nm * NAUTICAL_MILE_M
    return 120.0 + distance_m * math.tan(math.radians(SLOPE_DEG)) * math.cos(
        math.radians(beta_deg)
    )


def expected_tables() -> dict[str, Any]:
    """按固定 v2 坐标和归一化口径生成两张表。"""
    slope_rad = math.radians(SLOPE_DEG)
    q1_depths = [70.0 - distance * math.tan(slope_rad) for distance in DISTANCES_Q1]
    q1_halves = [coverage_halves(depth, OPENING_DEG, slope_rad) for depth in q1_depths]
    q1_widths = [deep + shallow for deep, shallow in q1_halves]
    overlaps: list[float | None] = [None]
    for index in range(1, len(DISTANCES_Q1)):
        spacing_horizontal = DISTANCES_Q1[index] - DISTANCES_Q1[index - 1]
        spacing_on_slope = spacing_horizontal / math.cos(slope_rad)
        previous_shallow = q1_halves[index - 1][1]
        current_deep = q1_halves[index][0]
        signed_overlap = previous_shallow + current_deep - spacing_on_slope
        overlaps.append(signed_overlap / q1_widths[index - 1])

    q2_rows: list[dict[str, Any]] = []
    for beta in BETAS_DEG:
        depths = [q2_depth(distance_nm, beta) for distance_nm in DISTANCES_Q2_NM]
        widths = [coverage_width(depth, SLOPE_DEG, OPENING_DEG, beta) for depth in depths]
        q2_rows.append(
            {
                "beta_deg": beta,
                "depth_m": depths,
                "coverage_width_m": widths,
            }
        )
    return {
        "q1": {
            "distances_m": list(DISTANCES_Q1),
            "depth_m": q1_depths,
            "coverage_width_m": q1_widths,
            "overlap_ratio": overlaps,
        },
        "q2": {"distances_nm": list(DISTANCES_Q2_NM), "rows": q2_rows},
    }


def _max_difference(actual: Sequence[float], expected: Sequence[float]) -> float:
    if len(actual) != len(expected):
        return math.inf
    try:
        return max(
            (abs(float(value) - float(reference)) for value, reference in zip(actual, expected)),
            default=0.0,
        )
    except (TypeError, ValueError):
        return math.inf


def validate_result(result: Mapping[str, Any], tolerance: float = 1e-6) -> dict[str, Any]:
    """由固定 v2 适配器独立复算并核验正式结果。"""
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
        try:
            differences.extend(
                abs(float(actual) - float(reference))
                for actual, reference in zip(
                    actual_overlaps[1:], expected["q1"]["overlap_ratio"][1:]
                )
            )
        except (TypeError, ValueError):
            differences.append(math.inf)

    try:
        actual_rows = {
            int(row["beta_deg"]): row["coverage_width_m"] for row in q2.get("rows", [])
        }
    except (KeyError, TypeError, ValueError):
        actual_rows = {}
    for expected_row in expected["q2"]["rows"]:
        differences.append(
            _max_difference(
                actual_rows.get(int(expected_row["beta_deg"]), []),
                expected_row["coverage_width_m"],
            )
        )
    maximum = max(differences, default=math.inf)
    return {
        "validator": "a092_2023b_q1_q2_v2",
        "formula_contract_version": "2023b_q1_q2_v2",
        "max_absolute_difference": maximum,
        "tolerance": tolerance,
        "objective_applicable": False,
        "constraints_applicable": False,
        "sensitivity_applicable": False,
        "valid": math.isfinite(maximum) and maximum <= tolerance,
        "expected": expected,
    }
