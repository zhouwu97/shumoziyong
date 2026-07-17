from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_problem_specific_evidence import (  # noqa: E402
    ProblemValidatorError,
    run_problem_validator,
)


def _report() -> dict[str, Any]:
    checks = [
        {
            "check_id": f"Q{index}-check",
            "expression": "independent recomputation",
            "observed": 1,
            "expected": 1,
            "unit": "m",
            "passed": True,
        }
        for index in range(1, 5)
    ]
    return {
        "schema_version": "1.0.0",
        "artifact_type": "problem_validator_report_v1",
        "validator_id": "problem-2023-b-validator-v1",
        "validator_version": "scaffold-1.0.0",
        "problem_id": "2023-B",
        "run_id": "validator-fixture-2023b",
        "subproblem_ids": ["Q1", "Q2", "Q3", "Q4"],
        "official_materials": {"path": "materials.json", "sha256": "0" * 64},
        "decision_variables": {"path": "variables.json", "sha256": "0" * 64},
        "objective_recomputation": {"checks": checks, "passed": True},
        "hard_constraint_recomputation": {"checks": checks, "passed": True},
        "unit_checks": {"checks": checks, "passed": True},
        "bound_checks": {"checks": checks, "passed": True},
        "required_outputs": [{"path": "result.xlsx", "sha256": "0" * 64}],
        "random_checks": {
            "seed": 2023,
            "sample_count": 32,
            "samples_hash": "1" * 64,
            "passed": True,
        },
        "candidate_self_attested": False,
        "independent_execution": True,
        "status": "passed",
        "failure_codes": [],
    }


def test_current_problem_validator_scaffolds_fail_closed(tmp_path: Path) -> None:
    registry = json.loads(
        (ROOT / "runtime_contracts/problem_validator_registry_v1.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ProblemValidatorError, match="scaffold_fail_closed"):
        run_problem_validator(_report(), case_root=tmp_path, registry=registry)


def test_candidate_self_attestation_is_never_validator_evidence() -> None:
    schema = json.loads(
        (ROOT / "schemas/problem_validator_report.schema.json").read_text(encoding="utf-8")
    )
    report = copy.deepcopy(_report())
    report["candidate_self_attested"] = True
    assert list(Draft202012Validator(schema).iter_errors(report))


def test_validator_report_must_bind_all_original_subproblems(tmp_path: Path) -> None:
    registry = json.loads(
        (ROOT / "runtime_contracts/problem_validator_registry_v1.json").read_text(encoding="utf-8")
    )
    registry["validators"][1]["status"] = "active"
    report = _report()
    report["subproblem_ids"] = ["Q1", "Q2", "Q3"]
    with pytest.raises(ProblemValidatorError, match="全部原始子问题"):
        run_problem_validator(report, case_root=tmp_path, registry=registry)
