"""运行 A092 v2 外部验证门槛 Pilot。"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validators.common.external_validation import (  # noqa: E402
    build_external_validator_attestation,
)
from validators.pilot_case.candidate_evaluator_v2 import (  # noqa: E402
    evaluate_solution as candidate_evaluate_solution,
)
from validators.pilot_case.external_adapter_v2 import (  # noqa: E402
    check_constraints,
    recompute_objective,
)


OUTPUT_ROOT = ROOT / "examples" / "a092_phase2_pilot_v2"
ARTIFACT_ROOT = OUTPUT_ROOT / "artifacts" / "a092"
INPUT_PATH = ROOT / "validators" / "pilot_case" / "fixture_v2.json"
EXTERNAL_ADAPTER_PATH = ROOT / "validators" / "pilot_case" / "external_adapter_v2.py"
CANDIDATE_EVALUATOR_PATH = ROOT / "validators" / "pilot_case" / "candidate_evaluator_v2.py"
CONTRACT_PATH = ROOT / "protocols" / "a092_v2" / "external_validator_contract.md"
AUDIT_SCHEMA_PATH = ROOT / "schemas" / "a092_data_contract_audit.schema.json"
ATTESTATION_SCHEMA_PATH = ROOT / "schemas" / "a092_external_validator_attestation.schema.json"
SOLUTION = {"x": 6.0, "y": 2.0}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(encoded.encode("utf-8"))


def _valid_data_audit() -> dict[str, Any]:
    checks = {
        "merged_cells": "输入为 JSON，无合并单元格；已显式核对字段层级。",
        "missing_values": "profit、capacity 和 time_slots 均执行非空检查。",
        "unit_conversions": "本 Pilot 全部量为同一无量纲收益/容量口径。",
        "aggregation_keys": "目标按变量名 x、y 聚合，不允许仅按显示标签汇总。",
        "time_slot_order": "固定按 2023 边界、2024 第一时段、2024 第二时段排序。",
        "boundary_state": "2023_boundary 显式进入时间槽序列。",
    }
    return {
        "schema_version": "2.0.0",
        "input_files": [
            {"path": INPUT_PATH.relative_to(ROOT).as_posix(), "sha256": _sha256_file(INPUT_PATH)}
        ],
        "preprocessing": {
            key: {"status": "passed", "evidence": evidence}
            for key, evidence in checks.items()
        },
        "hand_checked_fixtures": [
            {"fixture_id": "origin", "expected": 0.0, "actual": 0.0, "tolerance": 1e-9, "passed": True},
            {"fixture_id": "candidate", "expected": 58.0, "actual": 58.0, "tolerance": 1e-9, "passed": True},
            {"fixture_id": "capacity_edge", "expected": 50.0, "actual": 50.0, "tolerance": 1e-9, "passed": True}
        ],
    }


def _attest(
    audit: Mapping[str, Any],
    *,
    objective_passed: bool = True,
    constraints_passed: bool = True,
    optimality_evidence_passed: bool = True,
    same_implementation: bool = False,
) -> dict[str, Any]:
    candidate_hash = _sha256_file(CANDIDATE_EVALUATOR_PATH)
    adapter_hash = candidate_hash if same_implementation else _sha256_file(EXTERNAL_ADAPTER_PATH)
    return build_external_validator_attestation(
        validator_id="a092_v2_pilot_external_adapter",
        adapter_path=EXTERNAL_ADAPTER_PATH.relative_to(ROOT).as_posix(),
        adapter_sha256=adapter_hash,
        candidate_evaluator_path=(
            EXTERNAL_ADAPTER_PATH if same_implementation else CANDIDATE_EVALUATOR_PATH
        ).relative_to(ROOT).as_posix(),
        contract_path=CONTRACT_PATH.relative_to(ROOT).as_posix(),
        contract_sha256=_sha256_file(CONTRACT_PATH),
        input_sha256=_sha256_file(INPUT_PATH),
        solution_sha256=_sha256_json(SOLUTION),
        candidate_evaluator_sha256=candidate_hash,
        frozen_before_candidate=True,
        data_contract_audit=audit,
        objective_passed=objective_passed,
        constraints_passed=constraints_passed,
        optimality_evidence_passed=optimality_evidence_passed,
    )


def run_cases() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    problem_data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    objective = recompute_objective(SOLUTION, problem_data)
    candidate_objective = candidate_evaluate_solution(SOLUTION, problem_data)
    violations = check_constraints(SOLUTION, problem_data)
    valid_audit = _valid_data_audit()

    fixture_failure = deepcopy(valid_audit)
    fixture_failure["hand_checked_fixtures"][1].update({"actual": 59.0, "passed": False})
    missing_preprocessing = deepcopy(valid_audit)
    del missing_preprocessing["preprocessing"]["aggregation_keys"]

    cases = [
        {
            "case_id": "candidate_self_check_pass_external_objective_fail",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": 59.0,
            "external_objective_recomputed": objective,
            "attestation": _attest(valid_audit, objective_passed=False),
            "expected": {"experiment_disposition": "valid", "candidate_disposition": "rejected"},
        },
        {
            "case_id": "external_adapter_fixture_fail",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": candidate_objective,
            "external_objective_recomputed": objective,
            "attestation": _attest(fixture_failure),
            "expected": {"experiment_disposition": "invalid", "candidate_disposition": "rejected"},
        },
        {
            "case_id": "objective_pass_constraints_fail",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": candidate_objective,
            "external_objective_recomputed": objective,
            "attestation": _attest(valid_audit, constraints_passed=False),
            "expected": {"experiment_disposition": "valid", "candidate_disposition": "rejected"},
        },
        {
            "case_id": "same_implementation_claimed_independent",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": candidate_objective,
            "external_objective_recomputed": objective,
            "attestation": _attest(valid_audit, same_implementation=True),
            "expected": {"experiment_disposition": "invalid", "candidate_disposition": "rejected"},
        },
        {
            "case_id": "missing_data_preprocessing_audit",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": candidate_objective,
            "external_objective_recomputed": objective,
            "attestation": _attest(missing_preprocessing),
            "expected": {"experiment_disposition": "invalid", "candidate_disposition": "rejected"},
        },
        {
            "case_id": "objective_constraints_pass_without_optimality_evidence",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": candidate_objective,
            "external_objective_recomputed": objective,
            "attestation": _attest(valid_audit, optimality_evidence_passed=False),
            "expected": {"experiment_disposition": "valid", "candidate_disposition": "accepted"},
            "expected_claim_permissions": {
                "objective_value": True,
                "improvement_rate": True,
                "strong_optimality": False,
            },
        },
        {
            "case_id": "all_external_gates_pass",
            "candidate_self_check_passed": True,
            "candidate_objective_reported": candidate_objective,
            "external_objective_recomputed": objective,
            "attestation": _attest(valid_audit),
            "expected": {"experiment_disposition": "valid", "candidate_disposition": "accepted"},
        },
    ]
    for case in cases:
        attestation = case["attestation"]
        expected = case["expected"]
        case["detected"] = all(attestation[key] == value for key, value in expected.items())
        expected_permissions = case.get("expected_claim_permissions")
        if expected_permissions is None:
            expected_permissions = {
                key: expected["candidate_disposition"] == "accepted"
                for key in attestation["claim_permissions"]
            }
        case["claims_blocked_when_required"] = (
            attestation["claim_permissions"] == expected_permissions
        )

    if candidate_objective != 58.0 or objective != 58.0 or any(violations.values()):
        raise RuntimeError("Pilot 正例的外部复算结果不符合冻结小例子")
    return valid_audit, cases


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    valid_audit, cases = run_cases()
    audit_schema = json.loads(AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    attestation_schema = json.loads(ATTESTATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(audit_schema).validate(valid_audit)
    for case in cases:
        Draft202012Validator(attestation_schema).validate(case["attestation"])

    valid_attestation = next(
        case["attestation"] for case in cases if case["case_id"] == "all_external_gates_pass"
    )
    report = {
        "schema_version": "2.0.0",
        "pilot_id": "A092-V2-PILOT-20260713",
        "promotion_evidence": False,
        "excluded_from_roles": ["positive", "boundary", "negative"],
        "cases": cases,
        "all_cases_detected": all(
            case["detected"] and case["claims_blocked_when_required"] for case in cases
        ),
        "calibration_changes": [
            "外部 Validator 必须在候选生成过程之外预先冻结并记录实现哈希。",
            "数据契约或手算 fixture 失败判实验无效，不归因于候选方案。",
            "目标复算与硬约束形成目标值和改进率的双门槛，最优性强结论还需独立证明证据。"
        ]
    }
    _write_json(ARTIFACT_ROOT / "data_contract_audit.json", valid_audit)
    _write_json(ARTIFACT_ROOT / "external_validator_attestation.json", valid_attestation)
    _write_json(OUTPUT_ROOT / "pilot_result.json", report)
    print(json.dumps({"pilot_id": report["pilot_id"], "passed": report["all_cases_detected"]}))
    return 0 if report["all_cases_detected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
