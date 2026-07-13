"""M3A Run 专属 Sandboxie 执行证明与攻击回归。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.errors import FormalResultVerificationError
from formal_result.derivation import verify_formal_result_derivation
from formal_result.execution_contract import compile_execution_command
from formal_result.run_execution_attestation import (
    validate_execution_time_window,
    verify_run_execution_attestation,
)
from formal_result.trusted_local import collect_git_state
from formal_result.verifier import verify_formal_result_bundle
from run_workflow import verify_run


FIXTURE = ROOT / "tests" / "fixtures" / "m3a_verified_run"
FORMAL_RESULT_ID = "formal-m3a-fixture-001"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "run"
    shutil.copytree(FIXTURE, target)
    return target


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_real_sandboxie_fixture_propagates_eligibility_to_gate_evidence_seal_and_verify() -> None:
    summary = verify_formal_result_bundle(
        FIXTURE,
        FIXTURE / "formal_results" / FORMAL_RESULT_ID / "formal_result_envelope.json",
    )
    report = verify_run(FIXTURE)
    gate_3 = _load(FIXTURE / "gate_artifacts" / "gate_3.manifest.json")
    evidence = _load(FIXTURE / "run_evidence_manifest.json")
    seal = _load(FIXTURE / "seal_record.json")

    assert summary["formal_result_executed_in_verified_environment"] is True
    assert summary["formal_result_eligible"] is True
    assert gate_3["formal_result"]["formal_result_eligible"] is True
    assert evidence["formal_result_eligible"] is True
    assert seal["formal_result_eligible"] is True
    assert report["verified_gates"] == [0, 1, 2, 3, 4, 5]
    assert report["sealed"] is True
    assert report["formal_result_eligible"] is True


def test_verify_run_accepts_repository_relative_run_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    report = verify_run(Path("tests/fixtures/m3a_verified_run"))
    assert report["sealed"] is True
    assert report["formal_result_eligible"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_id", "different-run", "run_id"),
        ("formal_result_id", "different-formal-result", "formal_result_id"),
        ("execution_spec_sha256", "f" * 64, "execution_spec_sha256"),
        ("trusted_registry_sha256", "f" * 64, "trusted_registry_sha256"),
        ("trusted_key_entry_semantic_sha256", "f" * 64, "trusted_key_entry_semantic_sha256"),
    ],
)
def test_run_attestation_rejects_identity_and_trust_binding_drift(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    run = _copy(tmp_path)
    path = run / "sandboxie_run_execution_attestation.json"
    attestation = _load(path)
    attestation[field] = value
    _write(path, attestation)
    with pytest.raises(FormalResultVerificationError, match=message):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


@pytest.mark.parametrize("operation", ["add", "delete", "modify"])
def test_complete_code_manifest_rejects_file_set_or_hash_drift(
    tmp_path: Path, operation: str
) -> None:
    run = _copy(tmp_path)
    code = run / "workspace" / "code"
    if operation == "add":
        (code / "undeclared.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    elif operation == "delete":
        (code / "solve.py").unlink()
    else:
        (code / "solve.py").write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(FormalResultVerificationError, match="Code Manifest"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_input_modification_is_rejected(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    (run / "problem" / "input.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(FormalResultVerificationError, match="Input Manifest"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_execution_spec_modification_is_rejected(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    spec_path = run / "execution_spec.json"
    spec = _load(spec_path)
    spec["approved_by"] = "attacker"
    _write(spec_path, spec)
    with pytest.raises(FormalResultVerificationError, match="execution_spec_sha256"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


@pytest.mark.parametrize("link_kind", ["hardlink", "symlink"])
def test_code_manifest_rejects_link_files(
    tmp_path: Path, link_kind: str
) -> None:
    run = _copy(tmp_path)
    code = run / "workspace" / "code" / "solve.py"
    external = tmp_path / "external.py"
    external.write_bytes(code.read_bytes())
    code.unlink()
    try:
        if link_kind == "hardlink":
            os.link(external, code)
        else:
            code.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"当前平台不允许创建 {link_kind}：{exc}")
    with pytest.raises(FormalResultVerificationError, match="Code Manifest"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


@pytest.mark.parametrize("operation", ["add", "delete"])
def test_output_set_must_match_exactly(tmp_path: Path, operation: str) -> None:
    run = _copy(tmp_path)
    output = run / "workspace" / "output"
    if operation == "add":
        (output / "undeclared.json").write_text("{}\n", encoding="utf-8")
    else:
        (output / "result.json").unlink()
    with pytest.raises(FormalResultVerificationError, match="Output Manifest|raw output"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_machine_signature_modification_is_rejected(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    path = run / "sandboxie_run_execution_attestation.json"
    attestation = _load(path)
    signature = str(attestation["signature"])
    attestation["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    _write(path, attestation)
    with pytest.raises(FormalResultVerificationError, match="机器签名"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_registry_file_or_key_entry_change_is_rejected(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    registry_path = tmp_path / "trusted_environment_registry.json"
    registry = _load(ROOT / "policies" / "trusted_environment_registry.json")
    registry["keys"][0]["subject"] = "CN=Changed Trusted Key"
    _write(registry_path, registry)
    with pytest.raises(FormalResultVerificationError, match="trusted_registry_sha256"):
        verify_run_execution_attestation(
            run, FORMAL_RESULT_ID, registry_path=registry_path
        )


def test_outside_sandbox_record_cannot_receive_eligibility(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    record_path = run / "sandboxie_run_execution_record.json"
    record = _load(record_path)
    record["sandboxie_marker_detected"] = False
    _write(record_path, record)
    with pytest.raises(FormalResultVerificationError):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_missing_run_attestation_fails_closed_in_verify_run(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    (run / "sandboxie_run_execution_attestation.json").unlink()
    with pytest.raises(FormalResultVerificationError, match="attestation"):
        verify_run(run)


def test_expired_environment_refuses_new_execution_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _copy(tmp_path)
    import formal_result.run_execution_attestation as module

    original = module.load_and_verify_sandboxie_environment_report

    def expired(*args, **kwargs):
        summary = original(*args, **kwargs)
        summary["environment_attestation_currently_valid"] = False
        return summary

    monkeypatch.setattr(module, "load_and_verify_sandboxie_environment_report", expired)
    with pytest.raises(FormalResultVerificationError, match="过期"):
        verify_run_execution_attestation(
            run, FORMAL_RESULT_ID, require_current_environment=True
        )


def test_probe_sha_is_recomputed_from_source_commit(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    report_path = run / "sandboxie_environment_report.json"
    report = _load(report_path)
    report["collector"]["probe_script_sha256"] = "f" * 64
    for control in report["negative_controls"]:
        control["probe_sha256"] = "f" * 64
    _write(report_path, report)
    from formal_result.sandboxie_environment import load_and_verify_sandboxie_environment_report

    with pytest.raises(FormalResultVerificationError, match="source_commit"):
        load_and_verify_sandboxie_environment_report(
            report_path, run / "sandboxie_environment_attestation.json"
        )


def test_execution_command_compiler_preserves_args_working_directory_and_seed(
    tmp_path: Path,
) -> None:
    spec = _load(FIXTURE / "execution_spec.json")
    task = spec["tasks"][0]
    task["working_directory"] = "workspace/sub"
    task["argv"] = ["python", "../code/solve.py", "--mode", "validated"]
    task["seed_policy"]["seeds"] = [37]
    compiled = compile_execution_command(
        spec,
        tmp_path,
        execution_id="sandboxie-exec-command-test",
        challenge_nonce="a" * 64,
    )
    assert compiled["resolved_argv"] == [
        "python", "../code/solve.py", "--mode", "validated"
    ]
    assert compiled["resolved_working_directory"] == "sub"
    assert compiled["seed"] == 37
    assert compiled["environment_overrides"]["PYTHONHASHSEED"] == "37"
    assert compiled["environment_overrides"]["SHUMO_EXECUTION_CHALLENGE"] == "a" * 64


def test_execution_command_compiler_rejects_unsupported_acceptance_check(
    tmp_path: Path,
) -> None:
    spec = _load(FIXTURE / "execution_spec.json")
    spec["tasks"][0]["acceptance_checks"][0]["kind"] = "custom"
    with pytest.raises(FormalResultVerificationError, match="file_exists"):
        compile_execution_command(
            spec,
            tmp_path,
            execution_id="sandboxie-exec-command-test",
            challenge_nonce="b" * 64,
        )


def test_trusted_local_git_state_includes_untracked_and_staged_changes(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repository, check=True
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("stable\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repository, check=True)
    assert collect_git_state(repository)["git_state_clean"] is True

    (repository / "untracked.txt").write_text("drift\n", encoding="utf-8")
    assert collect_git_state(repository)["git_state_clean"] is False
    (repository / "untracked.txt").unlink()
    tracked.write_text("staged drift\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    state = collect_git_state(repository)
    assert state["git_state_clean"] is False
    assert state["diff_cached_exit_code"] == 1


def test_formal_result_must_derive_from_raw_sandbox_output(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    raw_path = run / "workspace" / "output" / "result.json"
    raw = _load(raw_path)
    raw["objective"] = 999
    _write(raw_path, raw)
    with pytest.raises(FormalResultVerificationError, match="raw output|Output Manifest"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_decision_variables_change_breaks_derivation_binding(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    decision_path = (
        run / "formal_results" / FORMAL_RESULT_ID / "decision_variables.json"
    )
    decision = _load(decision_path)
    decision["payload"]["x"] = 999
    _write(decision_path, decision)
    with pytest.raises(FormalResultVerificationError, match="core|raw output"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_derivation_contract_cannot_self_authorize_irrelevant_mapping(
    tmp_path: Path,
) -> None:
    run = _copy(tmp_path)
    contract = {
        "contract_version": "1.0.0",
        "raw_output_path": "result.json",
        "mappings": [
            {
                "source_pointer": "/objective",
                "target_artifact": "decision_variables.json",
                "target_pointer": "/payload/x",
            }
        ],
    }
    derivation_path = run / "collector_derivation_attestation.json"
    payload_path = run / "formal_result_payload_manifest.json"
    derivation = _load(derivation_path)
    payload = _load(payload_path)
    derivation["result_derivation_contract"] = contract
    payload["result_derivation_contract"] = contract
    _write(derivation_path, derivation)
    _write(payload_path, payload)
    with pytest.raises(FormalResultVerificationError, match="受信工程合同"):
        verify_formal_result_derivation(run, FORMAL_RESULT_ID)


def test_derivation_raw_output_path_cannot_escape_output(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    derivation_path = run / "collector_derivation_attestation.json"
    payload_path = run / "formal_result_payload_manifest.json"
    derivation = _load(derivation_path)
    payload = _load(payload_path)
    derivation["result_derivation_contract"]["raw_output_path"] = (
        "../../formal_results/formal-m3a-fixture-001/decision_variables.json"
    )
    payload["result_derivation_contract"] = derivation["result_derivation_contract"]
    _write(derivation_path, derivation)
    _write(payload_path, payload)
    with pytest.raises(FormalResultVerificationError, match="raw_output_path|Schema"):
        verify_formal_result_derivation(run, FORMAL_RESULT_ID)


def test_collector_script_must_match_bound_source_commit(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    derivation_path = run / "collector_derivation_attestation.json"
    derivation = _load(derivation_path)
    derivation["collector_script_sha256"] = "f" * 64
    _write(derivation_path, derivation)
    with pytest.raises(FormalResultVerificationError, match="Collector 脚本 SHA"):
        verify_formal_result_derivation(run, FORMAL_RESULT_ID)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("resolved_argv", ["python", "code/solve.py"], "execution_record_sha256|Execution Spec"),
        ("resolved_working_directory", "wrong", "execution_record_sha256|Execution Spec"),
        ("seed", 999, "execution_record_sha256|Execution Spec"),
        ("read_negative_controls", [], "execution_record_sha256|负控"),
        ("cleanup", {}, "execution_record_sha256|清理"),
        ("acceptance_results", [], "execution_record_sha256|acceptance"),
    ],
)
def test_execution_record_security_claims_cannot_drift(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    run = _copy(tmp_path)
    record_path = run / "sandboxie_run_execution_record.json"
    record = _load(record_path)
    record[field] = value
    _write(record_path, record)
    with pytest.raises(FormalResultVerificationError, match=message):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_execution_time_must_be_inside_environment_window(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    attestation_path = run / "sandboxie_run_execution_attestation.json"
    attestation = _load(attestation_path)
    attestation["started_at"] = "2026-07-01T00:00:00+08:00"
    _write(attestation_path, attestation)
    with pytest.raises(FormalResultVerificationError, match="started_at|时间窗口|绑定"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_challenge_echo_is_required(tmp_path: Path) -> None:
    run = _copy(tmp_path)
    challenge_path = run / "workspace" / "output" / "execution_challenge.json"
    challenge = _load(challenge_path)
    challenge["challenge_nonce"] = "f" * 64
    _write(challenge_path, challenge)
    with pytest.raises(FormalResultVerificationError, match="challenge|Output Manifest"):
        verify_run_execution_attestation(run, FORMAL_RESULT_ID)


def test_fixture_contains_real_child_stdout() -> None:
    stdout = FIXTURE / "execution_sandbox" / "output" / "stdout.log"
    assert stdout.read_text(encoding="utf-8").strip() == "formal test"


def test_fixture_binds_host_read_controls_and_cleanup() -> None:
    record = _load(FIXTURE / "sandboxie_run_execution_record.json")
    assert {
        item["control_id"] for item in record["read_negative_controls"]
    } == {
        "blocked_read_original_run",
        "blocked_read_repo_unlisted",
        "blocked_read_other_temp",
        "blocked_read_user_home",
    }
    assert all(item["status"] == "passed" for item in record["read_negative_controls"])
    assert record["execution_trust_model"] == "trusted_local"
    assert record["git_state_clean"] is True
    assert record["git_state"]["git_head"] == record["git_head"]
    assert record["git_state"]["status_porcelain_v1"] == ""
    assert record["privacy_mode_available"] is False
    assert record["targeted_host_read_controls_passed"] is True
    assert record["default_deny_host_reads_verified"] is False
    assert "UseRuleSpecificity=y" not in record["sandbox_policy_settings"]
    assert "UsePrivacyMode=y" not in record["sandbox_policy_settings"]
    assert record["cleanup"]["preexisting_configuration_restored"] is True
    assert record["cleanup"]["sandbox_paths_after"] == []


@pytest.mark.parametrize(
    ("started_at", "completed_at"),
    [
        ("2026-07-12T10:00:00+08:00", "2026-07-12T23:00:00+08:00"),
        ("2026-07-13T00:20:00+08:00", "2026-07-20T00:00:00+08:00"),
    ],
)
def test_execution_time_window_rejects_before_generation_or_after_expiry(
    started_at: str, completed_at: str
) -> None:
    with pytest.raises(FormalResultVerificationError, match="时间窗口"):
        validate_execution_time_window(
            "2026-07-12T22:57:58+08:00",
            started_at,
            completed_at,
            "2026-07-19T22:57:58+08:00",
        )
