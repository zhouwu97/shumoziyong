from __future__ import annotations

import math


def deg_to_rad(degrees: float) -> float:
    return math.radians(degrees)


def flat_coverage_width(depth_m: float, beam_angle_deg: float) -> float:
    if depth_m <= 0:
        raise ValueError("水深必须为正值")
    half_angle = deg_to_rad(beam_angle_deg / 2.0)
    return 2.0 * depth_m * math.tan(half_angle)


def effective_slope_deg(slope_deg: float, direction_beta_deg: float) -> float:
    # beta 为测线方向与坡面法向水平投影夹角，横向剖面取坡度在测线法向上的分量。
    slope = math.tan(deg_to_rad(slope_deg))
    beta = deg_to_rad(direction_beta_deg)
    return math.degrees(math.atan(slope * abs(math.sin(beta))))


def sloped_coverage_width(depth_m: float, beam_angle_deg: float, slope_deg: float) -> float:
    if depth_m <= 0:
        raise ValueError("水深必须为正值")
    half = math.tan(deg_to_rad(beam_angle_deg / 2.0))
    slope = math.tan(deg_to_rad(slope_deg))
    denominator = 1.0 - (half * slope) ** 2
    if denominator <= 0:
        raise ValueError("坡度与开角组合导致几何公式失效")
    return 2.0 * depth_m * half / denominator


def directional_coverage_width(
    depth_m: float,
    beam_angle_deg: float,
    slope_deg: float,
    direction_beta_deg: float,
) -> float:
    return sloped_coverage_width(
        depth_m=depth_m,
        beam_angle_deg=beam_angle_deg,
        slope_deg=effective_slope_deg(slope_deg, direction_beta_deg),
    )


def depth_on_slope(center_depth_m: float, offset_m: float, slope_deg: float) -> float:
    # offset 的正方向约定为向浅水侧移动；本函数只用于小样例，不代表最终坐标口径。
    depth = center_depth_m - offset_m * math.tan(deg_to_rad(slope_deg))
    if depth <= 0:
        raise ValueError("给定偏移处水深非正，请检查坐标方向或坡度")
    return depth


def main() -> None:
    beam_angle = 120.0
    slope = 1.5
    print("flat_width_70m:", round(flat_coverage_width(70.0, beam_angle), 3))
    print("sloped_width_70m:", round(sloped_coverage_width(70.0, beam_angle, slope), 3))
    print(
        "directional_width_beta_90:",
        round(directional_coverage_width(120.0, beam_angle, slope, 90.0), 3),
    )


if __name__ == "__main__":
    main()
