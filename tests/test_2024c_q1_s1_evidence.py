from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from official_integration import official_2024c_attachments
from scripts.validate_2024c_q1_s1 import build_s1_evidence


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.official_integration
def test_q1_s1_binds_formal_result_and_validator_report(tmp_path: Path) -> None:
    attachment_1, _ = official_2024c_attachments()
    material_root = attachment_1.parents[2]
    formal = ROOT / "formal_result/cases/2024_C/q1/q1_formal_result.json"
    run_log = ROOT / "formal_result/cases/2024_C/q1/q1_solver_run_log.json"
    material_manifest = ROOT / "formal_result/cases/2024_C/material_manifest.json"
    report, manifest = build_s1_evidence(
        material_root=material_root,
        formal_result_path=formal,
        run_log_path=run_log,
        material_manifest_path=material_manifest,
        report_path=tmp_path / "q1_validator_report.json",
        evidence_manifest_path=tmp_path / "q1_s1_evidence_manifest.json",
    )
    report_data = json.loads(report.read_text(encoding="utf-8"))
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/2024c_q1_s1_evidence_manifest.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(manifest_data)) == []
    assert report_data["valid"] is True
    assert report_data["production_ready"] is False
    assert report_data["formal_result_sha256"] == _sha256(formal)
    assert manifest_data["q1_baseline_frozen"] is False
    roles = {item["role"]: item for item in manifest_data["files"]}
    assert roles["formal_result"]["sha256"] == _sha256(formal)
    assert roles["validator_report"]["sha256"] == _sha256(report)
    assert {item["scenario_id"] for item in manifest_data["scenario_evidence"]} == {"q1_waste", "q1_discount"}


@pytest.mark.unit_contract
def test_q1_s1_rejects_run_log_bound_to_different_formal_result(tmp_path: Path) -> None:
    attachment_1, _ = official_2024c_attachments()
    material_root = attachment_1.parents[2]
    formal = ROOT / "formal_result/cases/2024_C/q1/q1_formal_result.json"
    run_log = tmp_path / "q1_solver_run_log.json"
    original = json.loads((ROOT / "formal_result/cases/2024_C/q1/q1_solver_run_log.json").read_text(encoding="utf-8"))
    original["formal_result_sha256"] = "0" * 64
    run_log.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="Formal Result SHA"):
        build_s1_evidence(
            material_root=material_root,
            formal_result_path=formal,
            run_log_path=run_log,
            material_manifest_path=ROOT / "formal_result/cases/2024_C/material_manifest.json",
            report_path=tmp_path / "report.json",
            evidence_manifest_path=tmp_path / "manifest.json",
        )
