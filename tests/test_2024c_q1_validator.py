from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from official_integration import official_2024c_attachments
from validators.problem_2024c_q1.validate import (
    check_q1_constraints,
    evaluate_q1_objective,
    load_q1_data,
    validate_q1_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_data() -> dict:
    return {
        "plots": {"A1": {"type": "平旱地", "area": 10.0}},
        "stats": {
            ("平旱地", "单季", 1): {"yield": 100.0, "cost": 10.0, "price": 2.0},
            ("平旱地", "单季", 2): {"yield": 100.0, "cost": 10.0, "price": 2.0},
        },
        "planting_2023": [{"year": 2023, "plot_id": "A1", "season": "单季", "crop_id": 1, "area_mu": 10.0}],
        "sales_2023": {(1, "单季"): 1000.0, (2, "单季"): 100.0},
        "price_by_crop_season": {(1, "单季"): 2.0, (2, "单季"): 2.0},
    }


@pytest.mark.official_integration
def test_official_loader_recovers_q1_input_shape() -> None:
    attachment_1, attachment_2 = official_2024c_attachments()
    data = load_q1_data(attachment_1, attachment_2)
    assert len(data["plots"]) == 54
    assert len(data["planting_2023"]) == 87
    assert data["plots"]["F1"]["type"] == "智慧大棚"


@pytest.mark.unit_contract
def test_q1_waste_and_discount_objectives_are_distinct() -> None:
    data = _synthetic_data()
    assignment = [{"year": 2024, "plot_id": "A1", "season": "单季", "crop_id": 2, "area_mu": 10.0}]
    assert evaluate_q1_objective(assignment, data, "q1_waste") == 100.0
    assert evaluate_q1_objective(assignment, data, "q1_discount") == 1000.0


@pytest.mark.unit_contract
def test_q1_constraints_fail_closed_on_capacity_and_suitability() -> None:
    data = _synthetic_data()
    bad = [{"year": 2024, "plot_id": "A1", "season": "单季", "crop_id": 99, "area_mu": 11.0}]
    violations, max_violation = check_q1_constraints(bad, data, check_legume_windows=False)
    assert any(item.startswith("suitability:") for item in violations)
    assert max_violation == 0.0


@pytest.mark.official_integration
def test_q1_formal_result_requires_both_scenarios_and_manifest_sha(tmp_path: Path) -> None:
    manifest = tmp_path / "material_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    result = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_formal_result",
        "problem_id": "2024-C",
        "material_manifest_sha256": digest,
        "scenarios": [
            {"scenario_id": scenario, "objective_reported": 0.0, "assignments": [], "output_workbook_status": "not_yet_generated"}
            for scenario in ("q1_waste", "q1_discount")
        ],
    }
    attachment_1, attachment_2 = official_2024c_attachments()
    report = validate_q1_result(result, attachment_1, attachment_2, manifest, check_legume_windows=False)
    assert report["valid"] is True
    assert report["production_ready"] is False
    result["scenarios"].pop()
    with pytest.raises(ValueError):
        validate_q1_result(result, attachment_1, attachment_2, manifest, check_legume_windows=False)
