"""A092 v2 外部 Validator 资格与论文 Claim 门槛。"""

from __future__ import annotations

import re
from typing import Any, Mapping


REQUIRED_PREPROCESSING_CHECKS = (
    "merged_cells",
    "missing_values",
    "unit_conversions",
    "aggregation_keys",
    "time_slot_order",
    "boundary_state",
)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def audit_data_contract(audit: Mapping[str, Any]) -> dict[str, Any]:
    """检查数据预处理审计和手算 fixture 是否足以支撑外部复算。"""

    preprocessing = audit.get("preprocessing")
    missing_checks: list[str] = []
    failed_checks: list[str] = []
    if not isinstance(preprocessing, Mapping):
        missing_checks.extend(REQUIRED_PREPROCESSING_CHECKS)
    else:
        for check in REQUIRED_PREPROCESSING_CHECKS:
            record = preprocessing.get(check)
            if not isinstance(record, Mapping):
                missing_checks.append(check)
            elif record.get("status") != "passed" or not str(record.get("evidence", "")).strip():
                failed_checks.append(check)

    fixtures = audit.get("hand_checked_fixtures")
    fixture_count = len(fixtures) if isinstance(fixtures, list) else 0
    fixtures_passed = (
        isinstance(fixtures, list)
        and 2 <= fixture_count <= 3
        and all(isinstance(item, Mapping) and item.get("passed") is True for item in fixtures)
    )
    input_files = audit.get("input_files")
    inputs_hashed = bool(input_files) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("path"), str)
        and SHA256_PATTERN.fullmatch(str(item.get("sha256", ""))) is not None
        for item in input_files
    )
    passed = not missing_checks and not failed_checks and fixtures_passed and inputs_hashed
    return {
        "missing_checks": missing_checks,
        "failed_checks": failed_checks,
        "fixture_count": fixture_count,
        "fixtures_passed": fixtures_passed,
        "inputs_hashed": inputs_hashed,
        "passed": passed,
    }


def build_external_validator_attestation(
    *,
    validator_id: str,
    adapter_path: str,
    adapter_sha256: str,
    candidate_evaluator_path: str,
    contract_path: str,
    contract_sha256: str,
    input_sha256: str,
    solution_sha256: str,
    candidate_evaluator_sha256: str,
    frozen_before_candidate: bool,
    data_contract_audit: Mapping[str, Any],
    objective_passed: bool,
    constraints_passed: bool,
    optimality_evidence_passed: bool,
) -> dict[str, Any]:
    """派生外部验证资格、候选判定和论文 Claim 权限。"""

    data_contract = audit_data_contract(data_contract_audit)
    hashes_present = all(
        SHA256_PATTERN.fullmatch(value) is not None
        for value in (
            adapter_sha256,
            contract_sha256,
            input_sha256,
            solution_sha256,
            candidate_evaluator_sha256,
        )
    )
    implementation_independent = bool(
        hashes_present
        and adapter_path != candidate_evaluator_path
        and adapter_sha256 != candidate_evaluator_sha256
    )
    reasons: list[str] = []
    if not frozen_before_candidate:
        reasons.append("validator_not_frozen_before_candidate")
    if not hashes_present:
        reasons.append("required_hash_missing")
    if not implementation_independent:
        reasons.append("validator_implementation_not_independent")
    if not data_contract["passed"]:
        reasons.append("data_contract_audit_failed")

    experiment_valid = not reasons
    candidate_valid = experiment_valid and objective_passed and constraints_passed
    if experiment_valid and not objective_passed:
        reasons.append("external_objective_failed")
    if experiment_valid and not constraints_passed:
        reasons.append("external_constraints_failed")

    claim_permissions = {
        "objective_value": candidate_valid,
        "improvement_rate": candidate_valid,
        "strong_optimality": candidate_valid and optimality_evidence_passed,
    }
    return {
        "schema_version": "2.0.0",
        "validator_id": validator_id,
        "status": "passed" if candidate_valid else "failed",
        "adapter_path": adapter_path,
        "adapter_sha256": adapter_sha256,
        "candidate_evaluator_path": candidate_evaluator_path,
        "contract_path": contract_path,
        "contract_sha256": contract_sha256,
        "input_sha256": input_sha256,
        "solution_sha256": solution_sha256,
        "candidate_evaluator_sha256": candidate_evaluator_sha256,
        "frozen_before_candidate": frozen_before_candidate,
        "implementation_independent": implementation_independent,
        "data_contract_passed": data_contract["passed"],
        "objective_passed": objective_passed,
        "constraints_passed": constraints_passed,
        "optimality_evidence_passed": optimality_evidence_passed,
        "experiment_disposition": "valid" if experiment_valid else "invalid",
        "candidate_disposition": "accepted" if candidate_valid else "rejected",
        "claim_permissions": claim_permissions,
        "failure_reasons": reasons,
    }
