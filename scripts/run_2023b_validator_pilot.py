"""运行 2023-B Validator v2 公式与故障注入 Pilot。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_bytes


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_OUTPUT = ROOT / "experiments" / "2023b_validator_pilot_v2" / "pilot_result.json"
SOURCE_PDF = ROOT / "official_materials" / "2023_B" / "problem" / "B题.pdf"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ray_plane_width(distance_nm: float, beta_deg: float) -> tuple[float, float]:
    """用三维射线与坡面求交复算船位水深和坡面覆盖宽度。"""
    alpha = math.radians(1.5)
    gamma = math.radians(60.0)
    beta = math.radians(beta_deg)
    distance_m = distance_nm * 1852.0
    ship_x = distance_m * math.cos(beta)
    ship_y = distance_m * math.sin(beta)
    cross_track = (-math.sin(beta), math.cos(beta), 0.0)
    points: list[tuple[float, float, float]] = []
    for sign in (-1.0, 1.0):
        ray = (
            sign * math.sin(gamma) * cross_track[0],
            sign * math.sin(gamma) * cross_track[1],
            math.cos(gamma),
        )
        parameter = (120.0 + ship_x * math.tan(alpha)) / (
            ray[2] - ray[0] * math.tan(alpha)
        )
        points.append(
            (
                ship_x + parameter * ray[0],
                ship_y + parameter * ray[1],
                parameter * ray[2],
            )
        )
    return 120.0 + ship_x * math.tan(alpha), math.dist(points[0], points[1])


def _fault_payloads(expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from validators.problem_boundary.validate import expected_tables as expected_tables_v1

    sign_flipped = copy.deepcopy(expected)
    by_beta = {row["beta_deg"]: row for row in expected["q2"]["rows"]}
    sign_flipped["q2"]["rows"] = [
        {
            "beta_deg": beta,
            "coverage_width_m": by_beta[(beta + 180) % 360]["coverage_width_m"],
        }
        for beta in (0, 45, 90, 135, 180, 225, 270, 315)
    ]

    flat_overlap = copy.deepcopy(expected)
    widths = flat_overlap["q1"]["coverage_width_m"]
    flat_overlap["q1"]["overlap_ratio"] = [
        None,
        *(1.0 - 200.0 / width for width in widths[1:]),
    ]

    horizontal_width = copy.deepcopy(expected)
    alpha = math.radians(1.5)
    for row in horizontal_width["q2"]["rows"]:
        beta = math.radians(row["beta_deg"])
        delta = math.atan(math.tan(alpha) * math.sin(beta))
        row["coverage_width_m"] = [
            width * math.cos(delta) for width in row["coverage_width_m"]
        ]

    degree_as_radian = copy.deepcopy(expected)
    gamma = math.radians(60.0)
    for row in degree_as_radian["q2"]["rows"]:
        beta_deg = row["beta_deg"]
        wrong_delta = math.atan(math.tan(alpha) * math.sin(beta_deg))
        depths = by_beta[beta_deg]["depth_m"]
        row["coverage_width_m"] = [
            depth
            * math.sin(gamma)
            * (
                1.0 / math.cos(gamma + wrong_delta)
                + 1.0 / math.cos(gamma - wrong_delta)
            )
            for depth in depths
        ]

    return {
        "v1_missing_directional_depth": expected_tables_v1(),
        "beta_direction_sign_flipped": sign_flipped,
        "flat_bottom_overlap_shortcut": flat_overlap,
        "horizontal_projection_as_width": horizontal_width,
        "degree_used_as_radian": degree_as_radian,
    }


def build_pilot_result() -> dict[str, Any]:
    from validators.problem_boundary_v2.validate import expected_tables, validate_result

    expected = expected_tables()
    checkpoints = []
    rows = {row["beta_deg"]: row for row in expected["q2"]["rows"]}
    for beta_deg, distance_nm in ((0, 0.3), (45, 0.6), (90, 2.1), (180, 2.1)):
        depth_ray, width_ray = _ray_plane_width(distance_nm, beta_deg)
        index = expected["q2"]["distances_nm"].index(distance_nm)
        depth_closed = rows[beta_deg]["depth_m"][index]
        width_closed = rows[beta_deg]["coverage_width_m"][index]
        checkpoints.append(
            {
                "beta_deg": beta_deg,
                "distance_nm": distance_nm,
                "depth_closed_form_m": depth_closed,
                "depth_ray_plane_m": depth_ray,
                "depth_absolute_difference_m": abs(depth_closed - depth_ray),
                "width_closed_form_m": width_closed,
                "width_ray_plane_m": width_ray,
                "width_absolute_difference_m": abs(width_closed - width_ray),
            }
        )

    faults = {
        fault_id: validate_result(payload)
        for fault_id, payload in _fault_payloads(expected).items()
    }
    fixed_contract = validate_result(expected)
    pilot_passed = (
        fixed_contract["valid"] is True
        and all(
            checkpoint["depth_absolute_difference_m"] <= 1e-10
            and checkpoint["width_absolute_difference_m"] <= 1e-10
            for checkpoint in checkpoints
        )
        and all(report["valid"] is False for report in faults.values())
        and math.isclose(
            faults["v1_missing_directional_depth"]["max_absolute_difference"],
            705.5840560000332,
            abs_tol=1e-8,
        )
    )
    return {
        "pilot_id": "2023b_validator_formula_pilot_v2",
        "source": {
            "path": SOURCE_PDF.relative_to(ROOT).as_posix(),
            "sha256": _sha256(SOURCE_PDF),
            "pages_checked": [2, 3],
        },
        "coordinate_contract": {
            "depth_axis": "vertical_down_positive",
            "q1_positive_distance": "shallow_direction",
            "q2_beta_zero": "deep_direction_from_upward_normal_horizontal_projection",
            "coverage_width_metric": "distance_along_seafloor_cross_section",
            "overlap_normalization": "signed_overlap_divided_by_previous_swath_width",
        },
        "equations": {
            "q1_depth": "D(x)=70-x*tan(alpha)",
            "q2_depth": "D(s,beta)=120+1852*s*tan(alpha)*cos(beta)",
            "cross_slope": "delta=atan(tan(alpha)*sin(beta))",
            "coverage_width": "W=D*sin(gamma)*(sec(gamma+delta)+sec(gamma-delta))",
        },
        "independent_ray_plane_checkpoints": checkpoints,
        "fixed_contract_validation": {
            key: fixed_contract[key]
            for key in ("validator", "max_absolute_difference", "tolerance", "valid")
        },
        "fault_injections": {
            fault_id: {
                key: report[key]
                for key in ("max_absolute_difference", "tolerance", "valid")
            }
            for fault_id, report in faults.items()
        },
        "pilot_passed": pilot_passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 2023-B Validator v2 公式 Pilot")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_pilot_result()
    atomic_write_bytes(
        args.output,
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({"output": str(args.output), "pilot_passed": result["pilot_passed"]}))
    return 0 if result["pilot_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
