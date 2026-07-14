"""Gate 3 证据必须绑定 Validator 语义，而非仅绑定自报标签。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gate3_evidence  # noqa: E402
from gate3_evidence import collect_gate_3_math_validation, validate_gate_3_check_evidence  # noqa: E402
import run_workflow  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "m3a_verified_run"
VALIDATOR_PATH = "validators/gate3_evidence_fixture/validate.py"
CONTRACT_PATH = "validators/gate3_evidence_fixture/gate_3_validator_contract.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict[str, object]:
    return {"profile": "engineering_optimization", "model_contract": {"optimization_checks": {"passed": ["constraint_residual"]}}}


def _manifest(*, deterministic: bool = True) -> dict[str, object]:
    return {"deterministic_expected": deterministic}


def _observation_spec(check_id: str) -> list[tuple[str, float, str, float]]:
    values = {
        "objective_recomputation": [
            ("reported_objective", 10.0, "eq", 10.0),
            ("recomputed_objective", 10.0, "eq", 10.0),
            ("absolute_error", 0.0, "le", 1e-6),
        ],
        "constraint_residual": [("max_constraint_residual", 0.0, "le", 1e-6)],
        "decision_output_consistency": [("decision_output_match", 1.0, "eq", 1.0)],
        "variable_domain": [("max_domain_violation", 0.0, "le", 1e-6)],
        "solver_status": [("solver_exit_code", 0.0, "eq", 0.0)],
        "random_seed_replay": [("replay_max_abs_error", 0.0, "le", 1e-12)],
        "sample_manifest_consistency": [("sample_manifest_match", 1.0, "eq", 1.0)],
    }
    return values[check_id]


def _refresh_report(run: Path, evidence: dict[str, object]) -> None:
    inputs = run / "validation" / "input_manifest.json"
    report = {
        "validator_path": VALIDATOR_PATH,
        "validator_sha256": _sha(ROOT / VALIDATOR_PATH),
        "input_manifest_sha256": _sha(inputs),
        "checks": [
            {
                "check_id": item["check_id"],
                "observations": [
                    {"name": observation["name"], "value": observation["value"]}
                    for observation in item["observations"]
                ],
            }
            for item in evidence["checks"]
        ],
    }
    path = run / "validation" / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    for item in evidence["checks"]:
        item["input_manifest_sha256"] = _sha(inputs)
        item["report_sha256"] = _sha(path)


def _evidence(run: Path, *, deterministic: bool = True) -> dict[str, object]:
    solution = run / "results" / "solution.json"
    solution.parent.mkdir(parents=True)
    solution.write_text('{"x": 1}\n', encoding="utf-8")
    inputs = run / "validation" / "input_manifest.json"
    inputs.parent.mkdir(parents=True)
    inputs.write_text(
        json.dumps({"artifacts": [{"path": "results/solution.json", "sha256": _sha(solution), "role": "candidate_solution"}]}),
        encoding="utf-8",
    )
    check_ids = [
        "objective_recomputation", "constraint_residual", "decision_output_consistency",
        "variable_domain", "solver_status",
    ]
    if not deterministic:
        check_ids.extend(["random_seed_replay", "sample_manifest_consistency"])
    evidence: dict[str, object] = {
        "schema_version": "1.0.0",
        "checks": [
            {
                "check_id": check_id,
                "check_type": "independent_recomputation",
                "validator_path": VALIDATOR_PATH,
                "validator_sha256": _sha(ROOT / VALIDATOR_PATH),
                "validator_contract_path": CONTRACT_PATH,
                "validator_contract_sha256": _sha(ROOT / CONTRACT_PATH),
                "input_manifest_path": "validation/input_manifest.json",
                "input_manifest_sha256": _sha(inputs),
                "report_path": "validation/report.json",
                "report_sha256": "0" * 64,
                "exit_code": 0,
                "observations": [
                    {"name": name, "value": value, "comparison": comparison, "threshold": threshold, "passed": True}
                    for name, value, comparison, threshold in _observation_spec(check_id)
                ],
                "passed": True,
            }
            for check_id in check_ids
        ],
    }
    _refresh_report(run, evidence)
    return evidence


def _write_evidence(run: Path, evidence: dict[str, object]) -> None:
    (run / "gate_3_check_evidence.json").write_text(json.dumps(evidence), encoding="utf-8")


def _use_isolated_validator_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 Validator 文件，允许负向测试安全篡改合同或报告 Schema。"""
    isolated_root = tmp_path / "repository"
    fixture_root = isolated_root / "validators" / "gate3_evidence_fixture"
    shutil.copytree(ROOT / "validators" / "gate3_evidence_fixture", fixture_root)
    schema_root = isolated_root / "schemas"
    schema_root.mkdir(parents=True)
    contract_schema = schema_root / "gate_3_validator_contract.schema.json"
    shutil.copy2(ROOT / "schemas" / "gate_3_validator_contract.schema.json", contract_schema)
    monkeypatch.setattr(gate3_evidence, "ROOT", isolated_root)
    monkeypatch.setattr(gate3_evidence, "CONTRACT_SCHEMA_PATH", contract_schema)
    return isolated_root


def test_plain_passed_string_cannot_grant_formal_eligibility(tmp_path: Path) -> None:
    result = collect_gate_3_math_validation(tmp_path, _report(), _manifest())
    assert result["structural_validation"] == "passed"
    assert result["mathematical_validation"] == "unverified"
    assert result["formal_result_eligible"] is False


def test_missing_validator_sha_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    del evidence["checks"][0]["validator_sha256"]
    assert validate_gate_3_check_evidence(evidence, tmp_path)


def test_missing_report_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    (tmp_path / "validation" / "report.json").unlink()
    errors = validate_gate_3_check_evidence(evidence, tmp_path)
    assert any("报告" in error and "文件不存在" in error for error in errors)


def test_tampered_report_hash_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    (tmp_path / "validation" / "report.json").write_text('{"tampered": true}', encoding="utf-8")
    assert any("报告 SHA-256" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_tampered_report_schema_hash_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    evidence = _evidence(run)
    isolated_root = _use_isolated_validator_root(tmp_path, monkeypatch)
    report_schema = isolated_root / "validators" / "gate3_evidence_fixture" / "report.schema.json"
    report_schema.write_text(report_schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    errors = validate_gate_3_check_evidence(evidence, run)
    assert any("报告 Schema SHA-256 不匹配" in error for error in errors)


def test_missing_report_schema_sha_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    evidence = _evidence(run)
    isolated_root = _use_isolated_validator_root(tmp_path, monkeypatch)
    contract_path = isolated_root / CONTRACT_PATH
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.pop("report_schema_sha256", None)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    for check in evidence["checks"]:
        check["validator_contract_sha256"] = _sha(contract_path)
    errors = validate_gate_3_check_evidence(evidence, run)
    assert any("report_schema_sha256" in error for error in errors)


def test_nonzero_exit_code_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence["checks"][0]["exit_code"] = 1
    assert any("exit_code" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_threshold_violation_rejected_even_when_claimed_passed(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence["checks"][0]["observations"][-1]["value"] = 100.0
    assert any("数值比较不一致" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_tampered_input_artifact_hash_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    (tmp_path / "results" / "solution.json").write_text('{"x": 999}\n', encoding="utf-8")
    assert any("artifact SHA-256" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_input_manifest_artifact_missing_sha_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    inputs = tmp_path / "validation" / "input_manifest.json"
    manifest = json.loads(inputs.read_text(encoding="utf-8"))
    del manifest["artifacts"][0]["sha256"]
    inputs.write_text(json.dumps(manifest), encoding="utf-8")
    _refresh_report(tmp_path, evidence)
    assert any("缺少 SHA-256" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_check_id_not_supported_by_validator_contract_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence["checks"][0]["check_id"] = "unrelated_claim"
    _refresh_report(tmp_path, evidence)
    assert any("不受 Validator Contract 支持" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_same_generic_report_cannot_impersonate_all_required_checks(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    report_path = tmp_path / "validation" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["checks"] = [report["checks"][0]]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    for check in evidence["checks"]:
        check["report_sha256"] = _sha(report_path)
    assert any("同名检查区段" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_report_check_id_mismatch_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    report_path = tmp_path / "validation" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["checks"][0]["check_id"] = "wrong_check"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    for check in evidence["checks"]:
        check["report_sha256"] = _sha(report_path)
    assert any("同名检查区段" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_missing_required_observation_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    report_path = tmp_path / "validation" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["checks"][0]["observations"].pop()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    for check in evidence["checks"]:
        check["report_sha256"] = _sha(report_path)
    assert any("缺少必需 observation" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_new_v2_run_cannot_advance_with_unverified_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    shutil.copytree(FIXTURE, run)
    formal_summary = run_workflow._verify_required_formal_result(run)
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["gate_3_evidence_contract_version"] = "1.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(run_workflow, "_verify_required_formal_result", lambda _run: formal_summary)
    with pytest.raises(ValueError, match="可执行数学检查证据失败"):
        run_workflow.verify_gate_artifacts(run, 3)


def test_legacy_run_remains_readable_but_ineligible(tmp_path: Path) -> None:
    result = collect_gate_3_math_validation(tmp_path, _report(), _manifest())
    assert result["mathematical_validation"] == "unverified"
    assert result["formal_result_eligible"] is False


def test_combined_validator_can_report_multiple_distinct_checks(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, deterministic=False)
    _write_evidence(tmp_path, evidence)
    result = collect_gate_3_math_validation(tmp_path, _report(), _manifest(deterministic=False))
    assert result["mathematical_validation"] == "passed"
    assert result["formal_result_eligible"] is True
