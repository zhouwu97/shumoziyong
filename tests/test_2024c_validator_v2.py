from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from validators.problem_positive.validate import load_problem_data as load_problem_data_v1
from validators.problem_positive_v2.validate import (
    check_constraints,
    evaluate_objective,
    load_problem_data,
)


ROOT = Path(__file__).resolve().parents[1]
ATTACHMENT_1 = ROOT / "official_materials" / "2024_C" / "attachments" / "附件1.xlsx"
ATTACHMENT_2 = ROOT / "official_materials" / "2024_C" / "attachments" / "附件2.xlsx"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def official_data() -> dict:
    if not ATTACHMENT_1.is_file() or not ATTACHMENT_2.is_file():
        pytest.skip("官方附件未在当前 checkout 中下载")
    return load_problem_data(ATTACHMENT_1, ATTACHMENT_2)


def test_v2_loader_recovers_merged_planting_rows(official_data: dict) -> None:
    v1 = load_problem_data_v1(ATTACHMENT_1, ATTACHMENT_2)

    assert len(v1["planting_2023"]) == 54
    assert len(v1["sales_2023"]) == 31
    assert len(official_data["planting_2023"]) == 87
    assert len(official_data["sales_2023"]) == 47


def test_v2_loader_uses_ordinary_greenhouse_for_smart_first_season(
    official_data: dict,
) -> None:
    stats = official_data["stats"]

    for crop_id in range(17, 35):
        assert stats[("智慧大棚", "第一季", crop_id)] == stats[
            ("普通大棚", "第一季", crop_id)
        ]
    assert stats[("智慧大棚", "第一季", 17)] != stats[("智慧大棚", "第二季", 17)]


def test_objective_caps_sales_by_crop_and_season() -> None:
    data = {
        "plots": {"F1": {"type": "智慧大棚", "area": 1.0}},
        "stats": {
            ("智慧大棚", "第一季", 17): {"yield": 100.0, "cost": 0.0, "price": 10.0},
            ("智慧大棚", "第二季", 17): {"yield": 100.0, "cost": 0.0, "price": 20.0},
        },
        "sales_2023": {(17, "第一季"): 50.0, (17, "第二季"): 10.0},
    }
    assignments = [
        {"year": 2024, "plot_id": "F1", "season": "第一季", "crop_id": 17, "area_mu": 1.0},
        {"year": 2024, "plot_id": "F1", "season": "第二季", "crop_id": 17, "area_mu": 1.0},
    ]

    assert evaluate_objective(assignments, data, "q1_waste") == 700.0
    assert evaluate_objective(assignments, data, "q1_discount") == 1850.0


def test_smart_greenhouse_rotation_uses_adjacent_actual_seasons() -> None:
    data = {
        "plots": {"F1": {"type": "智慧大棚", "area": 0.6}},
        "stats": {
            ("智慧大棚", season, crop): {"yield": 1.0, "cost": 0.0, "price": 1.0}
            for season in ("第一季", "第二季")
            for crop in (17, 18)
        },
        "planting_2023": [],
    }
    adjacent_repeat = [
        {"year": 2024, "plot_id": "F1", "season": "第一季", "crop_id": 17, "area_mu": 0.6},
        {"year": 2024, "plot_id": "F1", "season": "第二季", "crop_id": 17, "area_mu": 0.6},
    ]
    interrupted_repeat = [
        {"year": 2024, "plot_id": "F1", "season": "第一季", "crop_id": 17, "area_mu": 0.6},
        {"year": 2024, "plot_id": "F1", "season": "第二季", "crop_id": 18, "area_mu": 0.6},
        {"year": 2025, "plot_id": "F1", "season": "第一季", "crop_id": 17, "area_mu": 0.6},
    ]

    adjacent, _ = check_constraints(adjacent_repeat, data, 1e-6, check_legume_windows=False)
    interrupted, _ = check_constraints(interrupted_repeat, data, 1e-6, check_legume_windows=False)

    assert any(item.startswith("continuous_crop:") for item in adjacent)
    assert not any(item.startswith("continuous_crop:") for item in interrupted)


def test_official_price_is_constant_within_crop_season(official_data: dict) -> None:
    by_crop_season: dict[tuple[int, str], set[float]] = {}
    for (_plot_type, season, crop_id), stat in official_data["stats"].items():
        by_crop_season.setdefault((crop_id, season), set()).add(stat["price"])

    assert all(len(prices) == 1 for prices in by_crop_season.values())
    assert math.isclose(next(iter(by_crop_season[(17, "第一季")])), 8.0)


def test_diagnosis_separates_r01_candidate_error_from_r02_validator_error() -> None:
    diagnosis = json.loads(
        (
            ROOT
            / "experiments"
            / "2024c_objective_diagnosis_v1"
            / "diagnostic_result.json"
        ).read_text(encoding="utf-8")
    )

    assert diagnosis["diagnosis_passed"] is True
    assert all(
        not item["objective_valid"] for item in diagnosis["runs"]["R01"]["v2_report"]
    )
    assert all(
        item["objective_valid"] for item in diagnosis["runs"]["R02"]["v2_report"]
    )
    assert diagnosis["runs"]["R01"]["first_divergence"].startswith(
        "candidate_objective"
    )
    assert diagnosis["runs"]["R02"]["first_divergence"].startswith(
        "external_validator"
    )


def test_v2_validator_freeze_binds_diagnosis_and_code() -> None:
    freeze = json.loads(
        (
            ROOT / "protocols" / "a092_v2" / "2024c_validator_contract_freeze.json"
        ).read_text(encoding="utf-8")
    )

    assert freeze["status"] == "validator_frozen_for_a092_v2_design"
    assert freeze["full_confirmatory_protocol_frozen"] is False
    for relative, digest in freeze["official_inputs"].items():
        assert _sha256(ROOT / relative) == digest
    for relative, digest in freeze["validator_files"].items():
        assert _sha256(ROOT / relative) == digest
    assert _sha256(ROOT / freeze["diagnostic_result"]["path"]) == freeze[
        "diagnostic_result"
    ]["sha256"]
    assert _sha256(ROOT / freeze["diagnostic_report"]["path"]) == freeze[
        "diagnostic_report"
    ]["sha256"]
