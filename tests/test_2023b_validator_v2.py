from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from validators.problem_boundary.validate import expected_tables as expected_tables_v1
from validators.problem_boundary_v2.validate import (
    BETAS_DEG,
    DISTANCES_Q2_NM,
    expected_tables,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ray_plane_width(distance_nm: float, beta_deg: float) -> tuple[float, float]:
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
    width = math.dist(points[0], points[1])
    depth = 120.0 + ship_x * math.tan(alpha)
    return depth, width


def test_v2_closed_form_matches_independent_ray_plane_points() -> None:
    expected = expected_tables()
    rows = {row["beta_deg"]: row for row in expected["q2"]["rows"]}

    for beta_deg, distance_nm in ((0, 0.3), (45, 0.6), (90, 2.1), (180, 2.1)):
        depth, width = _ray_plane_width(distance_nm, beta_deg)
        distance_index = DISTANCES_Q2_NM.index(distance_nm)
        assert math.isclose(
            rows[beta_deg]["depth_m"][distance_index], depth, rel_tol=0, abs_tol=1e-10
        )
        assert math.isclose(
            rows[beta_deg]["coverage_width_m"][distance_index],
            width,
            rel_tol=0,
            abs_tol=1e-10,
        )


def test_v2_direction_convention_and_hand_checkpoints() -> None:
    expected = expected_tables()
    rows = {row["beta_deg"]: row for row in expected["q2"]["rows"]}

    assert math.isclose(rows[0]["depth_m"][1], 134.54889802383997, abs_tol=1e-10)
    assert math.isclose(rows[0]["coverage_width_m"][1], 466.0910549593899, abs_tol=1e-10)
    assert rows[0]["depth_m"][-1] > 120.0
    assert rows[180]["depth_m"][-1] < 120.0
    assert all(math.isclose(value, 120.0, abs_tol=1e-10) for value in rows[90]["depth_m"])
    assert all(math.isclose(value, 120.0, abs_tol=1e-10) for value in rows[270]["depth_m"])


def test_v2_q1_overlap_uses_signed_interval_and_previous_swath() -> None:
    q1 = expected_tables()["q1"]

    assert math.isclose(q1["overlap_ratio"][1], 0.33639959281203413, abs_tol=1e-12)
    assert q1["overlap_ratio"][-1] < 0


def test_v2_rejects_v1_missing_directional_depth_projection() -> None:
    report = validate_result(expected_tables_v1())

    assert report["valid"] is False
    assert math.isclose(report["max_absolute_difference"], 705.5840560000332, abs_tol=1e-8)


def test_v2_rejects_flipped_beta_direction() -> None:
    payload = expected_tables()
    by_beta = {row["beta_deg"]: row for row in payload["q2"]["rows"]}
    payload["q2"]["rows"] = [
        {"beta_deg": beta, "coverage_width_m": by_beta[(beta + 180) % 360]["coverage_width_m"]}
        for beta in BETAS_DEG
    ]

    assert validate_result(payload)["valid"] is False


def test_v2_rejects_flat_bottom_overlap_shortcut() -> None:
    payload = copy.deepcopy(expected_tables())
    widths = payload["q1"]["coverage_width_m"]
    payload["q1"]["overlap_ratio"] = [
        None,
        *(1.0 - 200.0 / width for width in widths[1:]),
    ]

    assert validate_result(payload)["valid"] is False


def test_v2_accepts_its_fixed_contract() -> None:
    report = validate_result(expected_tables())

    assert report["validator"] == "a092_2023b_q1_q2_v2"
    assert report["valid"] is True
    assert report["max_absolute_difference"] == 0


def test_v2_formula_freeze_binds_current_pilot_and_validator() -> None:
    freeze = json.loads(
        (ROOT / "protocols" / "a092_v2" / "2023b_validator_formula_freeze.json").read_text(
            encoding="utf-8"
        )
    )

    assert freeze["status"] == "formula_frozen_for_a092_v2_design"
    assert freeze["full_confirmatory_protocol_frozen"] is False
    for relative, digest in freeze["validator_files"].items():
        assert _sha256(ROOT / relative) == digest
    assert _sha256(ROOT / freeze["pilot_result"]["path"]) == freeze["pilot_result"]["sha256"]
    assert _sha256(ROOT / freeze["pilot_report"]["path"]) == freeze["pilot_report"]["sha256"]
