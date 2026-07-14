"""Gate 3 机器证据必须由 Collector 现场复核。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gate3_evidence import collect_gate_3_math_validation, validate_gate_3_check_evidence  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict[str, object]:
    return {"profile": "engineering_optimization", "model_contract": {"optimization_checks": {"passed": ["constraint_residual"]}}}


def _manifest(*, deterministic: bool = True) -> dict[str, object]:
    return {"deterministic_expected": deterministic}


def _evidence(run: Path, *, deterministic: bool = True) -> dict[str, object]:
    validator = ROOT / "validators" / "problem_negative" / "validate.py"
    inputs = run / "validation" / "input_manifest.json"
    report = run / "validation" / "report.json"
    inputs.parent.mkdir(parents=True)
    inputs.write_text('{"artifacts": []}\n', encoding="utf-8")
    report.write_text('{"ok": true}\n', encoding="utf-8")
    check_ids = [
        "objective_recomputation", "constraint_residual", "decision_output_consistency",
        "variable_domain", "solver_status",
    ]
    if not deterministic:
        check_ids.extend(["random_seed_replay", "sample_manifest_consistency"])
    return {
        "schema_version": "1.0.0",
        "checks": [
            {
                "check_id": check_id,
                "check_type": "independent_recomputation",
                "validator_path": "validators/problem_negative/validate.py",
                "validator_sha256": _sha(validator),
                "input_manifest_path": "validation/input_manifest.json",
                "input_manifest_sha256": _sha(inputs),
                "report_path": "validation/report.json",
                "report_sha256": _sha(report),
                "exit_code": 0,
                "observations": [{"name": "residual", "value": 0.0, "comparison": "le", "threshold": 1e-6, "passed": True}],
                "passed": True,
            }
            for check_id in check_ids
        ],
    }


def _write_evidence(run: Path, evidence: dict[str, object]) -> None:
    (run / "gate_3_check_evidence.json").write_text(json.dumps(evidence), encoding="utf-8")


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
    (tmp_path / "validation" / "report.json").write_text('{"ok": false}\n', encoding="utf-8")
    assert any("报告 SHA-256" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_nonzero_exit_code_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence["checks"][0]["exit_code"] = 1
    assert any("exit_code" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_threshold_violation_rejected_even_when_claimed_passed(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    observation = evidence["checks"][0]["observations"][0]
    observation["value"] = 100.0
    assert any("数值比较不一致" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_cross_run_report_path_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence["checks"][0]["report_path"] = "../other/report.json"
    assert any("越出当前 Run" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_unknown_comparison_operator_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    evidence["checks"][0]["observations"][0]["comparison"] = "approximately"
    assert validate_gate_3_check_evidence(evidence, tmp_path)


def test_cross_run_input_manifest_reference_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    inputs = tmp_path / "validation" / "input_manifest.json"
    inputs.write_text('{"artifacts": [{"path": "../other/result.json"}]}\n', encoding="utf-8")
    for check in evidence["checks"]:
        check["input_manifest_sha256"] = _sha(inputs)
    assert any("其他 Run" in error for error in validate_gate_3_check_evidence(evidence, tmp_path))


def test_complete_evidence_is_accepted(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    _write_evidence(tmp_path, evidence)
    result = collect_gate_3_math_validation(tmp_path, _report(), _manifest())
    assert result["mathematical_validation"] == "passed"
    assert result["formal_result_eligible"] is True


def test_legacy_record_remains_readable_but_ineligible(tmp_path: Path) -> None:
    result = collect_gate_3_math_validation(tmp_path, _report(), _manifest())
    assert result["mathematical_validation"] == "unverified"
    assert result["formal_result_eligible"] is False
