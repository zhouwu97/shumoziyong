from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from official_integration import official_2024c_attachments
from scripts.freeze_2024c_q1_baseline import freeze_q1_baseline


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.official_integration
def test_q1_s2_freezes_reverse_validated_workbook_baseline(tmp_path: Path) -> None:
    attachment_1, _ = official_2024c_attachments()
    material_root = attachment_1.parents[2]
    manifest_path = freeze_q1_baseline(
        material_root=material_root,
        formal_result_path=ROOT / "formal_result/cases/2024_C/q1/q1_formal_result.json",
        validator_report_path=ROOT / "formal_result/cases/2024_C/q1/q1_validator_report.json",
        material_manifest_path=ROOT / "formal_result/cases/2024_C/material_manifest.json",
        template_root=material_root,
        baseline_manifest_path=tmp_path / "q1_baseline_manifest.json",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/2024c_q1_baseline_manifest.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []
    assert manifest["q1_baseline_frozen"] is True
    assert manifest["official_workbook_reverse_validation_passed"] is True
    assert manifest["production_ready"] is False
    assert {item["scenario_id"] for item in manifest["scenarios"]} == {"q1_waste", "q1_discount"}
    assert all(item["workbook_validation_passed"] for item in manifest["scenarios"])
    assert all(item["template_path"].startswith("official_materials/") for item in manifest["scenarios"])


@pytest.mark.official_integration
def test_q1_s2_rejects_formal_result_area_drift(tmp_path: Path) -> None:
    attachment_1, _ = official_2024c_attachments()
    formal_path = ROOT / "formal_result/cases/2024_C/q1/q1_formal_result.json"
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    formal["scenarios"][0]["assignments"][0]["area_mu"] += 0.1
    altered = tmp_path / "altered_formal.json"
    altered.write_text(json.dumps(formal, ensure_ascii=False), encoding="utf-8")
    validator_report = json.loads((ROOT / "formal_result/cases/2024_C/q1/q1_validator_report.json").read_text(encoding="utf-8"))
    validator_report["formal_result_sha256"] = hashlib.sha256(altered.read_bytes()).hexdigest()
    altered_report = tmp_path / "altered_validator_report.json"
    altered_report.write_text(json.dumps(validator_report, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="决策变量集合|面积不一致"):
        freeze_q1_baseline(
            material_root=attachment_1.parents[2],
            formal_result_path=altered,
            validator_report_path=altered_report,
            material_manifest_path=ROOT / "formal_result/cases/2024_C/material_manifest.json",
            template_root=attachment_1.parents[2],
            baseline_manifest_path=tmp_path / "baseline.json",
        )
