from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from paper_content_quality import (  # noqa: E402
    build_content_delta_report,
    build_substantive_completeness_report,
    load_contract,
    _specific_roles,
)
from gate_f_status import build_gate_f_status  # noqa: E402
from gate_f_status import validate_f3_review_references  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix in {".yaml", ".yml"}:
        path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "contract.yaml"
    _write(
        path,
        {
            "schema_version": "1.0.0",
            "contract_id": "fixture_contract",
            "problem_id": "fixture",
            "role_requirements": {
                "Q1": [
                    {"role": "new_analysis", "severity": "critical"},
                    {"role": "interpretation", "severity": "major"},
                ]
            },
        },
    )
    return path


def _artifact(tmp_path: Path, name: str, text: str) -> dict[str, str]:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return {"path": name, "sha256": _sha(path), "formal_result_id": "fr-1"}


def _registry(tmp_path: Path, *, include_interpretation: bool) -> Path:
    source = _artifact(tmp_path, "formal.json", "formal result")
    validator = _artifact(tmp_path, "validator.json", "validator")
    paper = tmp_path / "paper" / "main.typ"
    paper.parent.mkdir(parents=True, exist_ok=True)
    paper.write_text("#q1\n#q1-interpretation\n", encoding="utf-8")
    roles = [
        {
            "role_id": "Q1_NEW_ANALYSIS",
            "question": "Q1",
            "role": "new_analysis",
            "severity": "critical",
            "applicability": "required",
            "status": "realized",
            "source_artifacts": [source],
            "validator_artifacts": [validator],
            "claim_ids": ["C001"],
            "paper_locations": ["paper/main.typ#q1"],
        }
    ]
    if include_interpretation:
        roles[0]["source_artifacts"][0]["shared"] = True
        roles[0]["validator_artifacts"][0]["shared"] = True
        roles.append(
            {
                "role_id": "Q1_INTERPRETATION",
                "question": "Q1",
                "role": "interpretation",
                "severity": "major",
                "applicability": "required",
                "status": "realized",
                "source_artifacts": [{**source, "shared": True}],
                "validator_artifacts": [{**validator, "shared": True}],
                "claim_ids": ["C002"],
                "paper_locations": ["paper/main.typ#q1-interpretation"],
            }
        )
    path = tmp_path / ("registry_full.json" if include_interpretation else "registry_thin.json")
    _write(
        path,
        {
            "schema_version": "1.0.0",
            "artifact_type": "paper_evidence_role_registry",
            "problem_id": "fixture",
            "contract_id": "fixture_contract",
            "run_id": "run-1",
            "formal_result_ids": ["fr-1"],
            "roles": roles,
        },
    )
    return path


def test_thin_candidate_fails_f2_with_major_gap(tmp_path: Path) -> None:
    report = build_substantive_completeness_report(
        _contract(tmp_path), _registry(tmp_path, include_interpretation=False), base_dir=tmp_path
    )

    assert report["status"] == "content_repair_required"
    assert report["required_role_coverage"] == 0.5
    assert report["critical_missing"] == []
    assert report["major_missing"][0]["role"] == "interpretation"


def test_complete_registry_passes_f2(tmp_path: Path) -> None:
    report = build_substantive_completeness_report(
        _contract(tmp_path), _registry(tmp_path, include_interpretation=True), base_dir=tmp_path, claim_ids={"C001", "C002"}
    )

    assert report["status"] == "passed"
    assert report["required_role_coverage"] == 1.0


def test_content_delta_requires_real_evidence_change(tmp_path: Path) -> None:
    before = _registry(tmp_path, include_interpretation=False)
    after = _registry(tmp_path, include_interpretation=True)
    report = build_content_delta_report(after, before_registry_path=before)

    assert report["substantive_paper_improvement"] is True
    assert report["new_technical_evidence"] is False
    assert report["new_paper_realization"] is True
    assert {item["role_id"] for item in report["deltas"]} == {"Q1_INTERPRETATION"}


def test_content_delta_requires_new_formal_result_for_new_clean_run(tmp_path: Path) -> None:
    before = _registry(tmp_path, include_interpretation=False)
    after = _registry(tmp_path, include_interpretation=True)
    payload = json.loads(after.read_text(encoding="utf-8"))
    payload["formal_result_ids"] = ["fr-2"]
    for role in payload["roles"]:
        for artifact in role["source_artifacts"] + role["validator_artifacts"]:
            artifact["formal_result_id"] = "fr-2"
            artifact["shared"] = True
    after.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = build_content_delta_report(after, before_registry_path=before)

    assert report["substantive_paper_improvement"] is True
    assert report["before_formal_result_ids"] == ["fr-1"]
    assert report["after_formal_result_ids"] == ["fr-2"]


def test_content_delta_reports_no_improvement_for_identical_registry(tmp_path: Path) -> None:
    registry = _registry(tmp_path, include_interpretation=True)
    report = build_content_delta_report(registry, before_registry_path=registry)

    assert report["substantive_paper_improvement"] is False
    assert report["deltas"] == []


def test_f1_pass_f2_fail_is_blocked_before_f3() -> None:
    status = build_gate_f_status(
        f1_passed=True,
        completeness_report={"status": "content_repair_required"},
    )

    assert status["status"] == "content_repair_required"
    assert status["eligible_for_gate_g"] is False


def test_only_f1_f2_f3_pass_allows_gate_g() -> None:
    f3_review = {
        "reviewer_type": "human",
        "reviewer_identity": "reviewer-1",
        "reviewed_candidate_id": "PC-0001",
        "candidate_sha256": "a" * 64,
        "completeness_report_sha256": "b" * 64,
        "decision": "approved",
        "critical_open": 0,
        "major_open": 0,
        "approval_record": "reviews/paper_reader/G5R-001.json",
    }
    status = build_gate_f_status(
        f1_passed=True,
        completeness_report={"status": "passed"},
        f3_status="passed",
        f3_review=f3_review,
    )

    assert status["status"] == "independent_paper_review_passed"
    assert status["eligible_for_gate_g"] is True


def test_f3_references_require_live_candidate_report_and_history(tmp_path: Path) -> None:
    candidate = tmp_path / "paper_candidate_manifest.json"
    candidate.write_text(json.dumps({"candidate_id": "PC-0001"}), encoding="utf-8")
    report = tmp_path / "paper_substantive_completeness_report.json"
    report.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    approval = tmp_path / "reviews" / "paper_reader" / "PRR-00000001.json"
    approval.parent.mkdir(parents=True)
    approval.write_text(json.dumps({"decision": "approved"}), encoding="utf-8")
    approval_sha = _sha(approval)
    (tmp_path / "paper_reader_review_history.jsonl").write_text(
        json.dumps({"path": "reviews/paper_reader/PRR-00000001.json", "sha256": approval_sha}) + "\n",
        encoding="utf-8",
    )
    review = {
        "reviewed_candidate_id": "PC-0001",
        "candidate_sha256": _sha(candidate),
        "completeness_report_sha256": _sha(report),
        "approval_record": "reviews/paper_reader/PRR-00000001.json",
    }
    validate_f3_review_references(tmp_path, review)
    review["candidate_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Candidate 不一致"):
        validate_f3_review_references(tmp_path, review)


def test_parent_contract_is_merged_and_cannot_be_weakened() -> None:
    contract = yaml.safe_load(
        (ROOT / "paper_content_contracts" / "2025_C_prediction_nipt_v1.yaml").read_text(encoding="utf-8")
    )
    merged = load_contract(ROOT / "paper_content_contracts" / "2025_C_prediction_nipt_v1.yaml")
    assert merged["inherited_contract_ids"] == ["generic_submission_v1"]
    roles = {(item["question"], item["role"]) for item in _specific_roles(merged)}
    assert {("thesis", "thesis"), ("model_definition", "model_definition"), ("Q1", "repeated_measurement_structure")} <= roles
    assert contract["parent_contract_id"] == "generic_submission_v1"


def test_2025_prediction_contract_contains_all_four_questions() -> None:
    contract = yaml.safe_load(
        (ROOT / "paper_content_contracts" / "2025_C_prediction_nipt_v1.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert set(contract["role_requirements"]) == {"Q1", "Q2", "Q3", "Q4"}
    assert all(contract["role_requirements"][question] for question in ("Q1", "Q2", "Q3", "Q4"))
    assert contract["binding_requirements"]["formal_result_required"] is True
