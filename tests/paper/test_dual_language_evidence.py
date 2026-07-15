from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_dual_language_evidence import check_dual_language_evidence  # noqa: E402


EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def manifest(path: str, digest_char: str) -> dict[str, str]:
    return {"path": path, "sha256": digest_char * 64}


def valid_execution_evidence() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "evidence_id": "dual-run-test",
        "example_only": False,
        "profile": {
            "profile_id": "cumcm_python_matlab_v1",
            "required_languages": ["python", "matlab"],
            "language_roles": {
                "python": "primary_solver",
                "matlab": "independent_reproducer",
            },
        },
        "executions": {
            "python": {
                "language": "python",
                "role": "primary_solver",
                "status": "executed",
                "verification_status": "verified",
                "execution_observed": True,
                "version": "Python 3.12.10",
                "dependencies": [{"name": "numpy", "version": "2.4.4"}],
                "command": ["python", "solver.py"],
                "cwd": "workspace/python",
                "started_at": "2026-07-15T09:00:00+08:00",
                "ended_at": "2026-07-15T09:01:00+08:00",
                "exit_code": 0,
                "stdout_sha256": "a" * 64,
                "stderr_sha256": EMPTY_SHA,
                "source_manifest": manifest("manifests/python_source.json", "b"),
                "input_manifest": manifest("inputs/shared_input.json", "c"),
                "output_manifest": manifest("outputs/python_output.json", "d"),
            },
            "matlab": {
                "language": "matlab",
                "role": "independent_reproducer",
                "status": "executed",
                "verification_status": "verified",
                "execution_observed": True,
                "version": "MATLAB R2025b",
                "toolboxes": [{"name": "Optimization Toolbox", "version": "25.2"}],
                "command": ["matlab", "-batch", "run_reproducer"],
                "cwd": "workspace/matlab",
                "started_at": "2026-07-15T09:02:00+08:00",
                "ended_at": "2026-07-15T09:04:00+08:00",
                "exit_code": 0,
                "stdout_sha256": "e" * 64,
                "stderr_sha256": EMPTY_SHA,
                "source_manifest": manifest("manifests/matlab_source.json", "f"),
                "input_manifest": manifest("inputs/shared_input.json", "c"),
                "output_manifest": manifest("outputs/matlab_output.json", "1"),
                "isolation": {
                    "invokes_python": False,
                    "reads_python_intermediates": False,
                    "input_origin": "shared_official_inputs",
                },
            },
        },
    }


def valid_cross_validation() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "validation_id": "cross-validation-test",
        "example_only": False,
        "execution_evidence_id": "dual-run-test",
        "output_manifests": {
            "python_sha256": "d" * 64,
            "matlab_sha256": "1" * 64,
        },
        "objective": {
            "metric": "total_cost",
            "direction": "minimize",
            "python_value": 1000.0,
            "matlab_value": 1000.0000001,
            "absolute_tolerance": 0.000001,
            "relative_tolerance": 0.000000001,
        },
        "hard_constraints": [
            {
                "constraint_id": "capacity_limit",
                "python": {"satisfied": True, "max_violation": 0.0},
                "matlab": {"satisfied": True, "max_violation": 0.0},
                "violation_tolerance": 0.00000001,
            }
        ],
        "business_aggregates": [
            {
                "aggregate_id": "supplier_count",
                "unit": "count",
                "python_value": 26,
                "matlab_value": 26,
                "absolute_tolerance": 0,
                "relative_tolerance": 0,
            }
        ],
        "optimality": {
            "python_status": "optimal",
            "matlab_status": "optimal",
        },
        "decision_variables": {
            "comparison_mode": "equivalent_optimum",
            "python_manifest_sha256": "2" * 64,
            "matlab_manifest_sha256": "3" * 64,
        },
    }


def issue_codes(report: dict[str, object]) -> set[str]:
    return {str(issue["code"]) for issue in report["issues"]}  # type: ignore[index, union-attr]


def run_check(
    execution: dict[str, object], validation: dict[str, object] | None = None
) -> dict[str, object]:
    return check_dual_language_evidence(execution, validation or valid_cross_validation())


def test_missing_python_execution() -> None:
    evidence = valid_execution_evidence()
    del evidence["executions"]["python"]  # type: ignore[index]

    report = run_check(evidence)

    assert report["passed"] is False
    assert "missing_python_execution" in issue_codes(report)


def test_missing_matlab_execution() -> None:
    evidence = valid_execution_evidence()
    del evidence["executions"]["matlab"]  # type: ignore[index]

    report = run_check(evidence)

    assert report["passed"] is False
    assert "missing_matlab_execution" in issue_codes(report)


def test_optional_matlab_not_required_by_profile() -> None:
    evidence = valid_execution_evidence()
    profile = evidence["profile"]  # type: ignore[index]
    profile["required_languages"] = ["python"]
    profile["language_roles"] = {"python": "primary_solver"}
    del evidence["executions"]["matlab"]  # type: ignore[index]

    report = run_check(evidence, {})

    assert report["passed"] is True
    assert report["cross_language_validation_required"] is False
    assert "missing_matlab_execution" not in issue_codes(report)


def test_required_matlab_missing_is_rejected() -> None:
    evidence = valid_execution_evidence()
    del evidence["executions"]["matlab"]  # type: ignore[index]

    report = run_check(evidence)

    assert report["passed"] is False
    assert report["cross_language_validation_required"] is True
    assert "missing_matlab_execution" in issue_codes(report)


def test_nonzero_exit_code() -> None:
    evidence = valid_execution_evidence()
    evidence["executions"]["python"]["exit_code"] = 1  # type: ignore[index]

    report = run_check(evidence)

    assert "nonzero_exit_code" in issue_codes(report)


def test_missing_source_manifest() -> None:
    evidence = valid_execution_evidence()
    del evidence["executions"]["python"]["source_manifest"]  # type: ignore[index]

    report = run_check(evidence)

    assert "missing_source_manifest" in issue_codes(report)


def test_missing_output_manifest() -> None:
    evidence = valid_execution_evidence()
    del evidence["executions"]["matlab"]["output_manifest"]  # type: ignore[index]

    report = run_check(evidence)

    assert "missing_output_manifest" in issue_codes(report)


def test_missing_toolbox_record() -> None:
    evidence = valid_execution_evidence()
    del evidence["executions"]["matlab"]["toolboxes"]  # type: ignore[index]

    report = run_check(evidence)

    assert "missing_toolbox_record" in issue_codes(report)


def test_cross_language_objective_mismatch() -> None:
    validation = valid_cross_validation()
    validation["objective"]["matlab_value"] = 1001.0  # type: ignore[index]

    report = run_check(valid_execution_evidence(), validation)

    assert "cross_language_objective_mismatch" in issue_codes(report)


def test_hard_constraint_mismatch() -> None:
    validation = valid_cross_validation()
    constraint = validation["hard_constraints"][0]  # type: ignore[index]
    constraint["matlab"]["satisfied"] = False
    constraint["matlab"]["max_violation"] = 0.1

    report = run_check(valid_execution_evidence(), validation)

    assert "hard_constraint_mismatch" in issue_codes(report)


def test_equivalent_optimum_allowed() -> None:
    report = run_check(valid_execution_evidence(), valid_cross_validation())

    assert report["passed"] is True
    assert report["status"] == "passed"
    assert report["issues"] == []


def test_unexecuted_source_claimed_as_verified() -> None:
    evidence = valid_execution_evidence()
    matlab = evidence["executions"]["matlab"]  # type: ignore[index]
    matlab["status"] = "not_run"
    matlab["execution_observed"] = False

    report = run_check(evidence)

    assert "unexecuted_source_claimed_as_verified" in issue_codes(report)


def test_missing_matlab_environment_is_blocked_not_passed() -> None:
    evidence = valid_execution_evidence()
    evidence["executions"]["matlab"] = {  # type: ignore[index]
        "language": "matlab",
        "role": "independent_reproducer",
        "status": "blocked_environment",
        "verification_status": "not_verified",
        "environment_blocker": {
            "reason": "MATLAB executable not found",
            "probe_command": ["matlab", "-batch", "version"],
            "observed_stderr_sha256": "4" * 64,
        },
    }

    report = run_check(evidence)

    assert report["passed"] is False
    assert report["status"] == "blocked_environment"
    assert "blocked_environment" in issue_codes(report)


def test_matlab_cannot_read_python_intermediates() -> None:
    evidence = copy.deepcopy(valid_execution_evidence())
    isolation = evidence["executions"]["matlab"]["isolation"]  # type: ignore[index]
    isolation["reads_python_intermediates"] = True

    report = run_check(evidence)

    assert "matlab_reads_python_intermediates" in issue_codes(report)


def test_matlab_cannot_invoke_python() -> None:
    evidence = copy.deepcopy(valid_execution_evidence())
    matlab = evidence["executions"]["matlab"]  # type: ignore[index]
    matlab["command"] = ["matlab", "-batch", "system('python helper.py')"]
    matlab["isolation"]["invokes_python"] = True

    report = run_check(evidence)

    assert "matlab_invokes_python" in issue_codes(report)


def test_business_aggregate_mismatch() -> None:
    validation = valid_cross_validation()
    aggregate = validation["business_aggregates"][0]  # type: ignore[index]
    aggregate["matlab_value"] = 27

    report = run_check(valid_execution_evidence(), validation)

    assert "business_aggregate_mismatch" in issue_codes(report)


def test_optimality_status_mismatch() -> None:
    validation = valid_cross_validation()
    validation["optimality"]["matlab_status"] = "feasible"  # type: ignore[index]

    report = run_check(valid_execution_evidence(), validation)

    assert "optimality_status_mismatch" in issue_codes(report)
