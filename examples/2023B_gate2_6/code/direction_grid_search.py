from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

GATE25_CODE = Path(__file__).resolve().parents[2] / "2023B_gate2_5" / "code"
sys.path.insert(0, str(GATE25_CODE))

from geometry_model import directional_coverage_width
from load_2023B_data import NM_TO_M, load_depth_grid
from overlap_check import check_overlap_interval


@dataclass(frozen=True)
class DirectionResult:
    direction_deg: float
    line_count: int
    total_length_m: float
    avg_coverage_width_m: float
    spacing_m: float
    projection_width_m: float
    overlap_status: str
    coverage_risk: str


def rectangle_corners(width_m: float, height_m: float) -> list[tuple[float, float]]:
    return [(0.0, 0.0), (width_m, 0.0), (width_m, height_m), (0.0, height_m)]


def projection_range(
    corners: list[tuple[float, float]], normal: tuple[float, float]
) -> tuple[float, float]:
    values = [x * normal[0] + y * normal[1] for x, y in corners]
    return min(values), max(values)


def clipped_line_length(
    width_m: float,
    height_m: float,
    direction: tuple[float, float],
    normal: tuple[float, float],
    offset_m: float,
) -> float:
    # 计算直线 n·p=offset 与矩形 [0,W]x[0,H] 的交段长度。
    ux, uy = direction
    nx, ny = normal
    cx, cy = width_m / 2.0, height_m / 2.0
    center_offset = cx * nx + cy * ny
    px = cx + (offset_m - center_offset) * nx
    py = cy + (offset_m - center_offset) * ny

    points: list[tuple[float, float]] = []
    eps = 1e-9

    if abs(ux) > eps:
        for x in (0.0, width_m):
            t = (x - px) / ux
            y = py + t * uy
            if -eps <= y <= height_m + eps:
                points.append((x, min(max(y, 0.0), height_m)))

    if abs(uy) > eps:
        for y in (0.0, height_m):
            t = (y - py) / uy
            x = px + t * ux
            if -eps <= x <= width_m + eps:
                points.append((min(max(x, 0.0), width_m), y))

    unique: list[tuple[float, float]] = []
    for point in points:
        if not any(abs(point[0] - old[0]) < 1e-6 and abs(point[1] - old[1]) < 1e-6 for old in unique):
            unique.append(point)

    if len(unique) < 2:
        return 0.0

    max_distance = 0.0
    for i, p1 in enumerate(unique):
        for p2 in unique[i + 1 :]:
            max_distance = max(max_distance, math.dist(p1, p2))
    return max_distance


def evaluate_direction(
    direction_deg: float,
    width_m: float,
    height_m: float,
    reference_depth_m: float,
    beam_angle_deg: float = 120.0,
    slope_deg: float = 1.5,
    target_overlap: float = 0.15,
) -> DirectionResult:
    angle = math.radians(direction_deg)
    direction = (math.cos(angle), math.sin(angle))
    normal = (-math.sin(angle), math.cos(angle))

    # 本轮用方向角作为坡面法向夹角的代理量，只用于粗网格 smoke-test。
    avg_width = directional_coverage_width(
        depth_m=reference_depth_m,
        beam_angle_deg=beam_angle_deg,
        slope_deg=slope_deg,
        direction_beta_deg=direction_deg,
    )
    spacing = avg_width * (1.0 - target_overlap)

    corners = rectangle_corners(width_m, height_m)
    low, high = projection_range(corners, normal)
    projection_width = high - low
    line_count = max(1, math.ceil(projection_width / spacing) + 1)
    start = low
    offsets = [start + i * spacing for i in range(line_count)]

    lengths = [
        clipped_line_length(width_m, height_m, direction, normal, offset)
        for offset in offsets
    ]
    total_length = sum(lengths)
    overlap_checks = [
        check_overlap_interval(spacing_m=spacing, coverage_width_m=avg_width).status
        for _ in range(max(0, line_count - 1))
    ]
    statuses = sorted(set(overlap_checks))
    overlap_status = ",".join(statuses) if statuses else "单线无相邻检查"

    covered_projection = (line_count - 1) * spacing + avg_width
    if covered_projection + 1e-6 >= projection_width and "通过" in overlap_status:
        coverage_risk = "低：投影宽度可覆盖，仍需真实地形复核"
    else:
        coverage_risk = "需复核：投影覆盖或重叠状态存在风险"

    return DirectionResult(
        direction_deg=direction_deg,
        line_count=line_count,
        total_length_m=total_length,
        avg_coverage_width_m=avg_width,
        spacing_m=spacing,
        projection_width_m=projection_width,
        overlap_status=overlap_status,
        coverage_risk=coverage_risk,
    )


def run_grid_search(directions: list[float] | None = None) -> list[DirectionResult]:
    if directions is None:
        directions = [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0]

    grid = load_depth_grid()
    summary = grid.summary()
    width_m = summary["x_range_m"][1] - summary["x_range_m"][0]
    height_m = summary["y_range_m"][1] - summary["y_range_m"][0]
    reference_depth_m = summary["depth_mean_m"]

    return [
        evaluate_direction(
            direction_deg=direction,
            width_m=width_m,
            height_m=height_m,
            reference_depth_m=reference_depth_m,
        )
        for direction in directions
    ]


def format_table(results: list[DirectionResult]) -> str:
    header = (
        "direction_deg,line_count,total_length_m,avg_coverage_width_m,"
        "spacing_m,projection_width_m,overlap_status,coverage_risk"
    )
    rows = [header]
    for result in results:
        rows.append(
            ",".join(
                [
                    f"{result.direction_deg:.0f}",
                    str(result.line_count),
                    f"{result.total_length_m:.3f}",
                    f"{result.avg_coverage_width_m:.3f}",
                    f"{result.spacing_m:.3f}",
                    f"{result.projection_width_m:.3f}",
                    result.overlap_status,
                    result.coverage_risk,
                ]
            )
        )
    return "\n".join(rows)


def main() -> None:
    print(format_table(run_grid_search()))


if __name__ == "__main__":
    main()
