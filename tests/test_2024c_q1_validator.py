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


def _write_test_manifest(
    tmp_path: Path,
    *,
    problem_id: str = "2024-C",
    include_attachment_2: bool = True,
) -> tuple[Path, Path, Path]:
    root = tmp_path / "materials"
    (root / "problem").mkdir(parents=True)
    (root / "attachments").mkdir()
    problem = root / "problem" / "C题.pdf"
    problem.write_bytes(b"problem")
    attachment_1 = root / "attachments" / "附件1.xlsx"
    attachment_2 = root / "attachments" / "附件2.xlsx"
    attachment_1.write_bytes(b"attachment-1")
    attachment_2.write_bytes(b"attachment-2")
    files = [
        {"path": "problem/C题.pdf", "sha256": hashlib.sha256(problem.read_bytes()).hexdigest()},
        {"path": "attachments/附件1.xlsx", "sha256": hashlib.sha256(attachment_1.read_bytes()).hexdigest()},
    ]
    if include_attachment_2:
        files.append({"path": "attachments/附件2.xlsx", "sha256": hashlib.sha256(attachment_2.read_bytes()).hexdigest()})
    manifest = {
        "manifest_version": "1.0.0",
        "problem_id": problem_id,
        "material_root": ".",
        "source": {"kind": "official", "reference": "unit-test"},
        "contains_answer_or_solution": False,
        "categories": {
            "problem": {"required": True, "files": [files[0]]},
            "attachments": {"required": True, "files": files[1:]},
            "templates": {"required": False, "files": []},
        },
    }
    manifest_path = root / "material_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path, attachment_1, attachment_2


def _empty_result(manifest_path: Path) -> dict:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_formal_result",
        "problem_id": "2024-C",
        "material_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "scenarios": [
            {"scenario_id": scenario, "objective_reported": 0.0, "assignments": [], "output_workbook_status": "not_yet_generated"}
            for scenario in ("q1_waste", "q1_discount")
        ],
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


@pytest.mark.unit_contract
def test_q1_constraints_detect_annual_rotation_for_non_greenhouse_plot() -> None:
    data = _synthetic_data()
    repeated = [{"year": 2024, "plot_id": "A1", "season": "单季", "crop_id": 1, "area_mu": 10.0}]
    interrupted = [
        {"year": 2024, "plot_id": "A1", "season": "单季", "crop_id": 2, "area_mu": 10.0},
        {"year": 2025, "plot_id": "A1", "season": "单季", "crop_id": 1, "area_mu": 10.0},
    ]
    repeated_violations, _ = check_q1_constraints(repeated, data, check_legume_windows=False)
    interrupted_violations, _ = check_q1_constraints(interrupted, data, check_legume_windows=False)
    assert any(item.startswith("continuous_crop:") for item in repeated_violations)
    assert not any(item.startswith("continuous_crop:") for item in interrupted_violations)


@pytest.mark.unit_contract
def test_q1_manifest_rejects_empty_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "material_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Manifest Schema"):
        validate_q1_result(
            _empty_result(manifest),
            tmp_path / "附件1.xlsx",
            tmp_path / "附件2.xlsx",
            manifest,
            check_legume_windows=False,
        )


@pytest.mark.unit_contract
def test_q1_manifest_rejects_wrong_problem_and_missing_role(tmp_path: Path) -> None:
    wrong_problem, attachment_1, attachment_2 = _write_test_manifest(tmp_path / "wrong", problem_id="2024-B")
    with pytest.raises(ValueError, match="题目不匹配"):
        validate_q1_result(_empty_result(wrong_problem), attachment_1, attachment_2, wrong_problem, check_legume_windows=False)

    missing_role, attachment_1, attachment_2 = _write_test_manifest(tmp_path / "missing", include_attachment_2=False)
    with pytest.raises(ValueError, match="缺少附件角色"):
        validate_q1_result(_empty_result(missing_role), attachment_1, attachment_2, missing_role, check_legume_windows=False)


@pytest.mark.unit_contract
def test_q1_manifest_rejects_non_official_source(tmp_path: Path) -> None:
    manifest, attachment_1, attachment_2 = _write_test_manifest(tmp_path)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["source"]["kind"] = "user_provided"
    manifest.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="只接受官方材料"):
        validate_q1_result(
            _empty_result(manifest),
            attachment_1,
            attachment_2,
            manifest,
            check_legume_windows=False,
        )


@pytest.mark.unit_contract
@pytest.mark.parametrize("attachment_number", [1, 2])
def test_q1_manifest_rejects_replaced_attachment(tmp_path: Path, attachment_number: int) -> None:
    manifest, attachment_1, attachment_2 = _write_test_manifest(tmp_path / "binding")
    replaced = attachment_1 if attachment_number == 1 else attachment_2
    replaced.write_bytes(b"tampered")
    result = _empty_result(manifest)
    with pytest.raises(ValueError, match="SHA-256"):
        validate_q1_result(result, attachment_1, attachment_2, manifest, check_legume_windows=False)


@pytest.mark.unit_contract
def test_q1_manifest_rejects_swapped_attachment_roles(tmp_path: Path) -> None:
    manifest, attachment_1, attachment_2 = _write_test_manifest(tmp_path / "binding")
    result = _empty_result(manifest)
    with pytest.raises(ValueError, match="路径未绑定"):
        validate_q1_result(result, attachment_2, attachment_1, manifest, check_legume_windows=False)


@pytest.mark.official_integration
def test_q1_generated_workbook_status_never_claims_production_ready() -> None:
    attachment_1, attachment_2 = official_2024c_attachments()
    manifest = attachment_1.parents[1] / "material_manifest.json"
    result = _empty_result(manifest)
    for scenario in result["scenarios"]:
        scenario.update({"output_workbook_status": "generated", "output_workbook_path": "fake.xlsx", "output_workbook_sha256": "a" * 64})
    report = validate_q1_result(result, attachment_1, attachment_2, manifest, check_legume_windows=False)
    assert report["valid"] is True
    assert report["production_ready"] is False


@pytest.mark.official_integration
def test_q1_formal_result_requires_both_scenarios_and_manifest_sha(tmp_path: Path) -> None:
    attachment_1, attachment_2 = official_2024c_attachments()
    manifest = attachment_1.parents[1] / "material_manifest.json"
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
    report = validate_q1_result(result, attachment_1, attachment_2, manifest, check_legume_windows=False)
    assert report["valid"] is True
    assert report["production_ready"] is False
    result["scenarios"].pop()
    with pytest.raises(ValueError):
        validate_q1_result(result, attachment_1, attachment_2, manifest, check_legume_windows=False)
