"""Gate 3 Validator 必须由父进程真实执行并绑定完整执行现场。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gate3_evidence import validate_gate_3_check_evidence  # noqa: E402
from gate3_executor import (  # noqa: E402
    Gate3ExecutionError,
    execute_gate_3_validator,
)


CONTRACT_PATH = "validators/gate3_evidence_fixture/gate_3_validator_contract.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_inputs(
    run_dir: Path,
    *,
    candidate_value: float = 2.0,
    fixture_mode: str | None = None,
) -> dict[str, list[str]]:
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    payloads: dict[str, object] = {
        "problem.json": {"target": 2.0, "lower_bound": 0.0, "upper_bound": 10.0},
        "candidate.json": {
            "x": candidate_value,
            "reported_objective": candidate_value**2,
            "sample_manifest_id": "fixture-sample",
        },
        "parameters.json": {
            "objective_coefficient": 1.0,
            "tolerance": 1e-6,
            "random_seed": 7,
            **({"fixture_mode": fixture_mode} if fixture_mode is not None else {}),
        },
        "solver_log.json": {"exit_code": 0, "replay_value": candidate_value},
    }
    for filename, payload in payloads.items():
        (inputs / filename).write_text(json.dumps(payload), encoding="utf-8")
    return {
        "problem_data": ["inputs/problem.json"],
        "candidate_solution": ["inputs/candidate.json"],
        "model_parameters": ["inputs/parameters.json"],
        "solver_log": ["inputs/solver_log.json"],
    }


def _execute(run_dir: Path, *, candidate_value: float = 2.0) -> dict[str, object]:
    return execute_gate_3_validator(
        run_dir,
        CONTRACT_PATH,
        _prepare_inputs(run_dir, candidate_value=candidate_value),
    )


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_prewritten_report_without_execution_is_rejected(tmp_path: Path) -> None:
    evidence = _execute(tmp_path)
    (tmp_path / "validation" / "execution_attestation.json").unlink()

    errors = validate_gate_3_check_evidence(evidence, tmp_path)

    assert any("执行证明" in error and "不存在" in error for error in errors)


def test_stale_report_is_deleted_before_execution(tmp_path: Path) -> None:
    validation = tmp_path / "validation"
    validation.mkdir()
    for filename in (
        "report.json",
        "execution_attestation.json",
        "stdout.log",
        "stderr.log",
    ):
        (validation / filename).write_text("stale-report", encoding="utf-8")
    (tmp_path / "gate_3_check_evidence.json").write_text("stale-evidence", encoding="utf-8")

    evidence = _execute(tmp_path)

    assert "stale-report" not in (validation / "report.json").read_text(encoding="utf-8")
    assert not validate_gate_3_check_evidence(evidence, tmp_path)


def test_validator_subprocess_is_actually_invoked(tmp_path: Path) -> None:
    evidence = _execute(tmp_path)
    attestation = _load(tmp_path / "validation" / "execution_attestation.json")

    assert attestation["exit_code"] == 0
    assert attestation["status"] == "completed"
    assert attestation["argv"][0] == attestation["python_executable"]
    assert "gate3 fixture validator executed" in (
        tmp_path / "validation" / "stdout.log"
    ).read_text(encoding="utf-8")
    assert not validate_gate_3_check_evidence(evidence, tmp_path)


def test_nonzero_process_exit_is_rejected(tmp_path: Path) -> None:
    artifacts = _prepare_inputs(tmp_path, fixture_mode="nonzero")

    with pytest.raises(Gate3ExecutionError, match="退出码"):
        execute_gate_3_validator(tmp_path, CONTRACT_PATH, artifacts)

    attestation = _load(tmp_path / "validation" / "execution_attestation.json")
    assert attestation["exit_code"] == 7
    assert attestation["status"] == "nonzero_exit"
    assert not (tmp_path / "gate_3_check_evidence.json").exists()


def test_timeout_is_rejected(tmp_path: Path) -> None:
    artifacts = _prepare_inputs(tmp_path, fixture_mode="timeout")

    with pytest.raises(Gate3ExecutionError, match="超时"):
        execute_gate_3_validator(tmp_path, CONTRACT_PATH, artifacts)

    attestation = _load(tmp_path / "validation" / "execution_attestation.json")
    assert attestation["exit_code"] == -1
    assert attestation["status"] == "timed_out"
    assert not (tmp_path / "gate_3_check_evidence.json").exists()


def _assert_execution_log_tampering_is_rejected(tmp_path: Path, filename: str) -> None:
    evidence = _execute(tmp_path)
    with (tmp_path / "validation" / filename).open("a", encoding="utf-8") as stream:
        stream.write("tampered")

    errors = validate_gate_3_check_evidence(evidence, tmp_path)

    assert any(filename in error and "SHA-256" in error for error in errors)


def test_stdout_tampering_is_rejected(tmp_path: Path) -> None:
    _assert_execution_log_tampering_is_rejected(tmp_path, "stdout.log")


def test_stderr_tampering_is_rejected(tmp_path: Path) -> None:
    _assert_execution_log_tampering_is_rejected(tmp_path, "stderr.log")


def test_execution_attestation_tampering_is_rejected(tmp_path: Path) -> None:
    evidence = _execute(tmp_path)
    attestation_path = tmp_path / "validation" / "execution_attestation.json"
    attestation = _load(attestation_path)
    attestation["duration_seconds"] = -1
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    evidence["execution_attestation_sha256"] = _sha(attestation_path)

    errors = validate_gate_3_check_evidence(evidence, tmp_path)

    assert any("执行证明" in error for error in errors)


def test_empty_input_set_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(Gate3ExecutionError, match="输入集合不能为空"):
        execute_gate_3_validator(tmp_path, CONTRACT_PATH, {})


def test_missing_required_input_role_is_rejected(tmp_path: Path) -> None:
    artifacts = _prepare_inputs(tmp_path)
    del artifacts["solver_log"]

    with pytest.raises(Gate3ExecutionError, match="solver_log"):
        execute_gate_3_validator(tmp_path, CONTRACT_PATH, artifacts)


def test_extra_input_rejected_when_exact_input_set(tmp_path: Path) -> None:
    artifacts = _prepare_inputs(tmp_path)
    extra = tmp_path / "inputs" / "candidate_notes.txt"
    extra.write_text("candidate-selected extra input", encoding="utf-8")
    artifacts["candidate_notes"] = ["inputs/candidate_notes.txt"]

    with pytest.raises(Gate3ExecutionError, match="额外输入角色"):
        execute_gate_3_validator(tmp_path, CONTRACT_PATH, artifacts)


def test_validator_report_changes_when_candidate_solution_changes(tmp_path: Path) -> None:
    first_run = tmp_path / "first"
    second_run = tmp_path / "second"
    _execute(first_run, candidate_value=2.0)
    _execute(second_run, candidate_value=3.0)

    first_report = _load(first_run / "validation" / "report.json")
    second_report = _load(second_run / "validation" / "report.json")

    assert first_report != second_report
    first_checks = {item["check_id"]: item for item in first_report["checks"]}
    second_checks = {item["check_id"]: item for item in second_report["checks"]}
    assert first_checks["objective_recomputation"] != second_checks["objective_recomputation"]
