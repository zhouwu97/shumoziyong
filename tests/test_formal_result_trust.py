"""Formal Result Trust-closeout 的攻击回归。"""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.canonicalization import canonical_bytes
from formal_result.errors import FormalResultVerificationError
from formal_result.hashing import file_sha256, semantic_sha256
from formal_result.path_safety import validate_contract_relative_path
from formal_result.verifier import verify_formal_result_bundle
from formal_result.sandboxie_environment import (
    load_and_validate_sandboxie_fixture_report,
    load_and_verify_sandboxie_environment_report,
)
from formal_result_fixtures import (
    write_formal_result_bundle,
    write_sandboxie_environment_report,
)
from executor_core import execute_spec
from run_workflow import (
    advance_run,
    build_run_evidence_manifest,
    create_new_problem_run,
    evidence_artifact_specs_for_workflow,
    verify_run_seal,
)
from test_repository_tooling import _v2_gate_0_run, _write_material_manifest


LIVE_SANDBOXIE_REPORT = (
    ROOT
    / "output"
    / "environment"
    / "sandboxie-m2"
    / "2026-07-12"
    / "sandboxie_environment_report.json"
)


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = _v2_gate_0_run(tmp_path)
    envelope = write_formal_result_bundle(run_dir)
    return run_dir, envelope


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rebind_domain(envelope_path: Path) -> None:
    formal = envelope_path.parent
    domain_path = formal / "domain_manifest.json"
    domain = _load(domain_path)
    envelope = _load(envelope_path)
    envelope["domain_manifest_file_sha256"] = file_sha256(domain_path)
    envelope["domain_manifest_semantic_sha256"] = semantic_sha256(domain)
    _write(envelope_path, envelope)


def _rebind_artifact(envelope_path: Path, relative: str) -> None:
    formal = envelope_path.parent
    artifact_path = formal / relative
    artifact = _load(artifact_path)
    domain_path = formal / "domain_manifest.json"
    domain = _load(domain_path)
    descriptor = next(item for item in domain["required_artifacts"] if item["path"] == relative)
    descriptor["file_sha256"] = file_sha256(artifact_path)
    descriptor["semantic_sha256"] = semantic_sha256(artifact)

    manifest_path = formal / "formal_result_manifest.json"
    manifest = _load(manifest_path)
    manifest["semantic_hashes"][relative] = semantic_sha256(artifact)
    _write(manifest_path, manifest)
    manifest_descriptor = next(
        item for item in domain["required_artifacts"] if item["path"] == "formal_result_manifest.json"
    )
    manifest_descriptor["file_sha256"] = file_sha256(manifest_path)
    manifest_descriptor["semantic_sha256"] = semantic_sha256(manifest)
    domain["semantic_hashes"] = {
        item["path"]: item["semantic_sha256"]
        for item in domain["required_artifacts"]
        if "semantic_sha256" in item
    }
    _write(domain_path, domain)

    envelope = _load(envelope_path)
    envelope["domain_manifest_file_sha256"] = file_sha256(domain_path)
    envelope["domain_manifest_semantic_sha256"] = semantic_sha256(domain)
    envelope["formal_result_manifest_file_sha256"] = file_sha256(manifest_path)
    envelope["formal_result_manifest_semantic_sha256"] = semantic_sha256(manifest)
    if relative == "collector_attestation.json":
        envelope["collector_attestation_semantic_sha256"] = semantic_sha256(artifact)
    _write(envelope_path, envelope)


def _rebind_execution_spec(run_dir: Path, envelope_path: Path) -> None:
    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    envelope = _load(envelope_path)
    envelope["execution_spec_file_sha256"] = file_sha256(spec_path)
    envelope["execution_spec_semantic_sha256"] = semantic_sha256(spec)
    _write(envelope_path, envelope)


def test_canonicalization_separates_semantics_from_format_and_preserves_array_order() -> None:
    left = {"b": 1.0, "a": [{"x": 1}, {"x": 2}]}
    same = {"a": [{"x": 1}, {"x": 2}], "b": 1.0000000001}
    reordered = {"a": [{"x": 2}, {"x": 1}], "b": 1.0}
    assert canonical_bytes(left) != canonical_bytes(same)
    assert canonical_bytes(left) != canonical_bytes(reordered)
    assert not canonical_bytes(left).endswith(b"\n")
    with pytest.raises(ValueError, match="NaN"):
        canonical_bytes({"bad": float("nan")})


def test_new_gate_runs_default_to_required_v1(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2026-B", {"problem": [("problem.pdf", problem)]})
    args = Namespace(
        run_id="formal-default", output_root=str(tmp_path / "runs"), problem="2026-B",
        profile="general", gates="0-5", materials=str(materials), candidate_patch=[],
        exclude_patch=[], material_file=[], promotion_evidence=False, experiment_group_id=None,
        experiment_role=None, target_patch=None, workflow="new_problem", mode="standard",
    )
    run_dir, ready = create_new_problem_run(args)
    manifest = _load(run_dir / "run_manifest.json")
    assert ready is True
    assert manifest["formal_result_policy"] == "required_v1"
    assert manifest["canonicalization_version"] == "1.0.0"


def test_required_bundle_verifies_and_binds_file_and_semantic_hashes(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    summary = verify_formal_result_bundle(run_dir, envelope)
    assert summary["formal_result_id"] == "formal-test-001"
    assert summary["envelope_file_sha256"] != summary["envelope_semantic_sha256"]
    assert summary["formal_result_activation_status"] == "code_complete_candidate"
    assert summary["formal_result_eligible"] is False


def test_fixture_report_never_activates_environment_or_eligibility(tmp_path: Path) -> None:
    report_path = write_sandboxie_environment_report(tmp_path)
    fixture = load_and_validate_sandboxie_fixture_report(report_path)
    assert fixture["sandboxie_environment_observed"] is True
    assert fixture["sandboxie_environment_verified"] is False
    assert fixture["formal_result_eligible"] is False
    with pytest.raises(FormalResultVerificationError, match="Fixture 报告"):
        load_and_verify_sandboxie_environment_report(report_path)


def test_signed_sandboxie_report_verifies_environment_but_not_run_eligibility(
    tmp_path: Path,
) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    envelope = write_formal_result_bundle(run_dir, sandboxie_report=LIVE_SANDBOXIE_REPORT)
    summary = verify_formal_result_bundle(run_dir, envelope)
    assert summary["formal_result_activation_status"] == "sandboxie_environment_verified"
    assert summary["sandboxie_environment_observed"] is True
    assert summary["sandboxie_environment_verified"] is True
    assert summary["formal_result_executed_in_verified_environment"] is False
    assert summary["formal_result_eligible"] is False

    run_manifest = _load(run_dir / "run_manifest.json")
    workflow = str(run_manifest["workflow"])
    for relative, _role, _media_type in evidence_artifact_specs_for_workflow(workflow):
        path = run_dir / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
    evidence = build_run_evidence_manifest(run_dir, str(run_manifest["run_id"]))
    roles = {item["role"] for item in evidence["artifacts"]}
    assert "sandboxie_environment_report" in roles
    assert "sandboxie_environment_attestation" in roles
    assert "sandboxie_configuration_backup" in roles
    assert evidence["sandboxie_environment_observed"] is True
    assert evidence["sandboxie_environment_verified"] is True
    assert evidence["formal_result_executed_in_verified_environment"] is False
    assert evidence["formal_result_eligible"] is False

    transitions_path = run_dir / "transitions.jsonl"
    transitions_path.write_text("{}\n", encoding="utf-8")
    evidence_path = run_dir / "run_evidence_manifest.json"
    _write(evidence_path, evidence)
    environment = summary["sandboxie_environment"]
    seal = {
        "seal_version": "1.0.0",
        "run_id": run_manifest["run_id"],
        "sealed_at": "2026-07-12T12:00:00+08:00",
        "run_manifest_sha256": file_sha256(run_dir / "run_manifest.json"),
        "transitions_sha256": file_sha256(transitions_path),
        "evidence_manifest_sha256": file_sha256(evidence_path),
        **{
            field: run_manifest[field]
            for field in (
                "formal_result_policy",
                "execution_contract_version",
                "formal_result_contract_version",
                "canonicalization_version",
                "gate_artifact_contract_version",
            )
        },
        "formal_result_id": summary["formal_result_id"],
        "formal_result_envelope_sha256": summary["envelope_file_sha256"],
        "formal_result_envelope_semantic_sha256": summary["envelope_semantic_sha256"],
        "formal_result_activation_status": summary["formal_result_activation_status"],
        "sandboxie_environment_observed": True,
        "sandboxie_environment_verified": True,
        "formal_result_executed_in_verified_environment": False,
        "formal_result_eligible": False,
        "sandboxie_environment_report_id": environment["report_id"],
        "sandboxie_environment_report_sha256": environment["report_file_sha256"],
        "sandboxie_environment_report_semantic_sha256": environment[
            "report_semantic_sha256"
        ],
        "sandboxie_environment_attestation_sha256": environment[
            "attestation_file_sha256"
        ],
        "sandboxie_environment_attestation_semantic_sha256": environment[
            "attestation_semantic_sha256"
        ],
        "sandboxie_environment_original_report_sha256": environment[
            "original_report_sha256"
        ],
        "sandboxie_environment_fingerprint": environment["environment_fingerprint"],
        "sandboxie_environment_machine_key_id": environment["machine_key_id"],
        "sandboxie_configuration_backup_sha256": environment[
            "configuration_backup_sha256"
        ],
    }
    _write(run_dir / "seal_record.json", seal)
    assert verify_run_seal(run_dir)["sandboxie_environment_verified"] is True

    report_path = run_dir / "sandboxie_environment_report.json"
    report_path.write_text(report_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(FormalResultVerificationError, match="报告绑定"):
        verify_run_seal(run_dir)


def test_sandboxie_configuration_backup_tampering_blocks_verification(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    envelope = write_formal_result_bundle(run_dir, sandboxie_report=LIVE_SANDBOXIE_REPORT)
    (run_dir / "sandboxie_config_backup.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(FormalResultVerificationError, match="配置备份"):
        verify_formal_result_bundle(run_dir, envelope)


def test_formal_result_id_rejects_windows_reserved_name(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    envelope = write_formal_result_bundle(run_dir, formal_result_id="CON")
    with pytest.raises(FormalResultVerificationError, match="formal_result_id"):
        verify_formal_result_bundle(run_dir, envelope)


@pytest.mark.parametrize("value", ["workspace/foo.", "workspace/foo ", "workspace/foo.."])
def test_contract_path_rejects_windows_trailing_dot_or_space(value: str) -> None:
    with pytest.raises(ValueError, match="尾随"):
        validate_contract_relative_path(value, "workspace", "测试路径")


def test_required_bundle_rejects_hardlinked_core_file(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    decision_path = envelope.parent / "decision_variables.json"
    external_path = tmp_path / "external_decision_variables.json"
    external_path.write_bytes(decision_path.read_bytes())
    decision_path.unlink()
    os.link(external_path, decision_path)

    with pytest.raises(FormalResultVerificationError, match="禁止 hardlink"):
        verify_formal_result_bundle(run_dir, envelope)


def test_required_bundle_rejects_hardlinked_execution_spec(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    spec_path = run_dir / "execution_spec.json"
    external_path = tmp_path / "external_execution_spec.json"
    external_path.write_bytes(spec_path.read_bytes())
    spec_path.unlink()
    os.link(external_path, spec_path)

    with pytest.raises(FormalResultVerificationError, match="禁止 hardlink"):
        verify_formal_result_bundle(run_dir, envelope)


def test_required_bundle_rejects_symlinked_execution_spec(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    spec_path = run_dir / "execution_spec.json"
    external_path = tmp_path / "external_execution_spec.json"
    external_path.write_bytes(spec_path.read_bytes())
    spec_path.unlink()
    try:
        spec_path.symlink_to(external_path)
    except OSError as exc:
        pytest.skip(f"当前平台不允许创建测试 symlink：{exc}")

    with pytest.raises(FormalResultVerificationError, match="禁止符号链接"):
        verify_formal_result_bundle(run_dir, envelope)


@pytest.mark.parametrize("link_kind", ["hardlink", "symlink"])
def test_executor_rejects_linked_execution_spec(tmp_path: Path, link_kind: str) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    spec_path = run_dir / "execution_spec.json"
    external_path = tmp_path / "linked_execution_spec.json"
    external_path.write_bytes(spec_path.read_bytes())
    spec_path.unlink()
    try:
        if link_kind == "hardlink":
            os.link(external_path, spec_path)
        else:
            spec_path.symlink_to(external_path)
    except OSError as exc:
        pytest.skip(f"当前平台不允许创建测试 {link_kind}：{exc}")

    with pytest.raises(ValueError, match="禁止"):
        execute_spec(spec_path, run_dir, "test-executor")


@pytest.mark.parametrize(
    "relative_spec",
    [
        Path("..") / "outside" / "execution_spec.json",
        Path("sub") / ".." / ".." / "outside" / "execution_spec.json",
    ],
)
def test_executor_only_accepts_canonical_run_spec(
    tmp_path: Path, relative_spec: Path
) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    outside = tmp_path / "outside" / "execution_spec.json"
    outside.parent.mkdir()
    outside.write_bytes((run_dir / "execution_spec.json").read_bytes())

    with pytest.raises(ValueError, match="execution_spec.json"):
        execute_spec(run_dir / relative_spec, run_dir, "test-executor")


@pytest.mark.parametrize("field", ["problem_id", "profile", "runtime_pack_sha256"])
def test_executor_rejects_full_identity_drift(tmp_path: Path, field: str) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    spec[field] = "f" * 64 if field == "runtime_pack_sha256" else "different"
    _write(spec_path, spec)

    with pytest.raises(ValueError, match="不可变身份"):
        execute_spec(spec_path, run_dir, "test-executor")


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-c", "print('unbound')"],
        ["python", "-m", "unbound_module"],
    ],
)
def test_executor_rejects_unbound_python_modes(tmp_path: Path, argv: list[str]) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    spec["tasks"][0]["argv"] = argv
    _write(spec_path, spec)

    with pytest.raises(ValueError, match="entrypoint"):
        execute_spec(spec_path, run_dir, "test-executor")


@pytest.mark.parametrize(
    "runner_token",
    ["./python", "workspace/python", "/tmp/python", r"C:\fake\python.exe"],
)
def test_executor_rejects_path_based_python_runner_before_execution(
    tmp_path: Path, runner_token: str
) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    forged_output = run_dir / "workspace" / "output" / "forged.json"
    fake_runner = run_dir / "workspace" / "python"
    fake_runner.write_text(
        "#!/usr/bin/env python\n"
        "from pathlib import Path\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/forged.json').write_text('{}', encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake_runner.chmod(0o755)
    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    spec["tasks"][0]["argv"][0] = runner_token
    _write(spec_path, spec)

    with pytest.raises(ValueError, match="python"):
        execute_spec(spec_path, run_dir, "test-executor")
    assert not forged_output.exists()


def test_executor_resolves_argv_entrypoint_from_working_directory(tmp_path: Path) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    unbound = run_dir / "workspace" / "sub" / "code" / "unbound.py"
    unbound.parent.mkdir(parents=True)
    unbound.write_text("print('unbound')\n", encoding="utf-8")
    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    task = spec["tasks"][0]
    task["working_directory"] = "workspace/sub"
    task["argv"] = ["python", "code/unbound.py"]
    _write(spec_path, spec)

    with pytest.raises(ValueError, match="entrypoint"):
        execute_spec(spec_path, run_dir, "test-executor")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("declared_workspace", "workspace/.."),
        ("working_directory", "workspace/.."),
        ("entrypoint", "code/../x.py"),
        ("input", "problem/../x"),
        ("output", "workspace/output/../../x"),
    ],
)
def test_execution_spec_path_traversal_fails_closed(
    tmp_path: Path, field: str, value: str
) -> None:
    run_dir, envelope = _bundle(tmp_path)
    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    task = spec["tasks"][0]
    if field == "declared_workspace":
        spec[field] = value
    elif field == "input":
        task["inputs"] = [{"path": value, "sha256": "a" * 64}]
    elif field == "output":
        task["required_outputs"][0]["path"] = value
    else:
        task[field] = value
    _write(spec_path, spec)
    _rebind_execution_spec(run_dir, envelope)

    with pytest.raises(FormalResultVerificationError):
        verify_formal_result_bundle(run_dir, envelope)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("execution_spec.json", "execution_spec.json 不存在"),
        ("formal_results/formal-test-001/domain_manifest.json", "domain_manifest.json 不存在"),
        ("formal_results/formal-test-001/decision_variables.json", "精确文件集不匹配"),
    ],
)
def test_deleting_required_core_artifact_fails_closed(
    tmp_path: Path, target: str, message: str
) -> None:
    run_dir, envelope = _bundle(tmp_path)
    (run_dir / target).unlink()
    with pytest.raises(FormalResultVerificationError, match=message):
        verify_formal_result_bundle(run_dir, envelope)


def test_policy_or_contract_version_drift_fails_closed(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    manifest = _load(run_dir / "run_manifest.json")
    manifest["formal_result_policy"] = "legacy_read_only_v1"
    _write(run_dir / "run_manifest.json", manifest)
    with pytest.raises(FormalResultVerificationError, match="required_v1"):
        verify_formal_result_bundle(run_dir, envelope)

    manifest["formal_result_policy"] = "required_v1"
    manifest["canonicalization_version"] = "2.0.0"
    _write(run_dir / "run_manifest.json", manifest)
    with pytest.raises(FormalResultVerificationError, match="canonicalization_version"):
        verify_formal_result_bundle(run_dir, envelope)


def test_format_only_json_change_can_rebind_file_hash_without_semantic_drift(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    formal = envelope.parent
    decision_path = formal / "decision_variables.json"
    decision = _load(decision_path)
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    domain = _load(formal / "domain_manifest.json")
    descriptor = next(item for item in domain["required_artifacts"] if item["path"] == "decision_variables.json")
    old_semantic = descriptor["semantic_sha256"]
    descriptor["file_sha256"] = file_sha256(decision_path)
    assert semantic_sha256(decision) == old_semantic
    _write(formal / "domain_manifest.json", domain)
    _rebind_domain(envelope)
    verify_formal_result_bundle(run_dir, envelope)


def test_semantic_change_with_same_filename_is_rejected(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    formal = envelope.parent
    decision_path = formal / "decision_variables.json"
    decision = _load(decision_path)
    decision["payload"] = {"x": 999}
    _write(decision_path, decision)
    domain = _load(formal / "domain_manifest.json")
    descriptor = next(item for item in domain["required_artifacts"] if item["path"] == "decision_variables.json")
    descriptor["file_sha256"] = file_sha256(decision_path)
    _write(formal / "domain_manifest.json", domain)
    _rebind_domain(envelope)
    with pytest.raises(FormalResultVerificationError, match="semantic_sha256"):
        verify_formal_result_bundle(run_dir, envelope)


@pytest.mark.parametrize(
    ("relative", "field", "value", "message"),
    [
        (
            "decision_variables.json",
            "artifact_type",
            "negative_tests",
            "artifact_type",
        ),
        (
            "optimization_validation.json",
            "status",
            "feasible",
            "status",
        ),
        ("negative_tests.json", "status", "feasible", "status"),
    ],
)
def test_filename_type_and_status_are_fixed(
    tmp_path: Path, relative: str, field: str, value: str, message: str
) -> None:
    run_dir, envelope = _bundle(tmp_path)
    artifact_path = envelope.parent / relative
    artifact = _load(artifact_path)
    artifact[field] = value
    _write(artifact_path, artifact)
    _rebind_artifact(envelope, relative)

    with pytest.raises(FormalResultVerificationError, match=message):
        verify_formal_result_bundle(run_dir, envelope)


def test_decision_schema_must_match_descriptor(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    domain_path = envelope.parent / "domain_manifest.json"
    domain = _load(domain_path)
    descriptor = next(
        item for item in domain["required_artifacts"] if item["path"] == "decision_variables.json"
    )
    descriptor["schema"] = "formal_result_core_artifact.schema.json"
    _write(domain_path, domain)
    _rebind_domain(envelope)

    with pytest.raises(FormalResultVerificationError, match="decision_schema"):
        verify_formal_result_bundle(run_dir, envelope)


def test_optimality_claim_must_match_certificate(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    domain_path = envelope.parent / "domain_manifest.json"
    domain = _load(domain_path)
    domain["optimality_claim_level"] = "feasible"
    _write(domain_path, domain)
    _rebind_domain(envelope)

    with pytest.raises(FormalResultVerificationError, match="optimality_claim_level"):
        verify_formal_result_bundle(run_dir, envelope)


def test_invariant_and_negative_test_requirements_are_executable(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    validation_path = envelope.parent / "optimization_validation.json"
    validation = _load(validation_path)
    validation["payload"]["invariant_checks"]["capacity"]["status"] = "failed"
    _write(validation_path, validation)
    _rebind_artifact(envelope, "optimization_validation.json")
    with pytest.raises(FormalResultVerificationError, match="领域不变量未通过"):
        verify_formal_result_bundle(run_dir, envelope)

    negative_root = tmp_path / "negative"
    negative_root.mkdir()
    run_dir, envelope = _bundle(negative_root)
    negative_path = envelope.parent / "negative_tests.json"
    negative = _load(negative_path)
    negative["payload"]["results"].pop()
    _write(negative_path, negative)
    _rebind_artifact(envelope, "negative_tests.json")
    with pytest.raises(FormalResultVerificationError, match="negative_test_requirements"):
        verify_formal_result_bundle(run_dir, envelope)


@pytest.mark.parametrize(
    "field",
    [
        "input_manifest_sha256",
        "code_manifest_sha256",
        "execution_spec_sha256",
        "environment_manifest_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "negative_test_report_sha256",
    ],
)
def test_attestation_hashes_are_recomputed(tmp_path: Path, field: str) -> None:
    run_dir, envelope = _bundle(tmp_path)
    attestation_path = envelope.parent / "collector_attestation.json"
    attestation = _load(attestation_path)
    attestation[field] = "f" * 64
    _write(attestation_path, attestation)
    _rebind_artifact(envelope, "collector_attestation.json")

    with pytest.raises(FormalResultVerificationError, match=field):
        verify_formal_result_bundle(run_dir, envelope)


def test_attestation_requires_no_candidate_access_and_exact_outputs(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    attestation_path = envelope.parent / "collector_attestation.json"
    attestation = _load(attestation_path)
    attestation["candidate_output_access_not_detected"] = False
    _write(attestation_path, attestation)
    _rebind_artifact(envelope, "collector_attestation.json")
    with pytest.raises(FormalResultVerificationError, match="candidate_output_access_not_detected"):
        verify_formal_result_bundle(run_dir, envelope)

    output_root = tmp_path / "outputs"
    output_root.mkdir()
    run_dir, envelope = _bundle(output_root)
    attestation_path = envelope.parent / "collector_attestation.json"
    attestation = _load(attestation_path)
    attestation["output_file_set"].append("undeclared.json")
    _write(attestation_path, attestation)
    _rebind_artifact(envelope, "collector_attestation.json")
    with pytest.raises(FormalResultVerificationError, match="output_file_set"):
        verify_formal_result_bundle(run_dir, envelope)


def test_verifier_recomputes_input_file_hash(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    (run_dir / "problem" / "input.txt").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(FormalResultVerificationError, match="输入.*哈希"):
        verify_formal_result_bundle(run_dir, envelope)


@pytest.mark.parametrize("link_kind", ["hardlink", "symlink"])
def test_verifier_rejects_linked_input_file(tmp_path: Path, link_kind: str) -> None:
    run_dir, envelope = _bundle(tmp_path)
    input_path = run_dir / "problem" / "input.txt"
    external = tmp_path / "external_input.txt"
    external.write_bytes(input_path.read_bytes())
    input_path.unlink()
    try:
        if link_kind == "hardlink":
            os.link(external, input_path)
        else:
            input_path.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"当前平台不允许创建测试 {link_kind}：{exc}")

    with pytest.raises(FormalResultVerificationError, match="禁止"):
        verify_formal_result_bundle(run_dir, envelope)


def test_output_file_set_cannot_be_self_attested(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    domain_path = envelope.parent / "domain_manifest.json"
    domain = _load(domain_path)
    domain["output_file_set"] = ["fake.json"]
    _write(domain_path, domain)
    _rebind_domain(envelope)

    attestation_path = envelope.parent / "collector_attestation.json"
    attestation = _load(attestation_path)
    attestation["output_file_set"] = ["fake.json"]
    _write(attestation_path, attestation)
    _rebind_artifact(envelope, "collector_attestation.json")

    with pytest.raises(FormalResultVerificationError, match="output_file_set"):
        verify_formal_result_bundle(run_dir, envelope)


def test_domain_manifest_has_independent_evidence_role(tmp_path: Path) -> None:
    run_dir, _envelope = _bundle(tmp_path)
    run_manifest = _load(run_dir / "run_manifest.json")
    workflow = str(run_manifest["workflow"])
    for relative, _role, _media_type in evidence_artifact_specs_for_workflow(workflow):
        path = run_dir / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
    evidence = build_run_evidence_manifest(run_dir, str(run_manifest["run_id"]))
    roles = {item["role"] for item in evidence["artifacts"]}
    assert "formal_result_domain_manifest" in roles
    assert evidence["formal_result_activation_status"] == "code_complete_candidate"
    assert evidence["formal_result_eligible"] is False


def test_required_v1_seal_schema_requires_formal_result_binding() -> None:
    from jsonschema import Draft202012Validator

    schema = _load(ROOT / "schemas" / "run_seal.schema.json")
    incomplete = {
        "seal_version": "1.0.0",
        "run_id": "run-1",
        "sealed_at": "2026-07-12T10:00:00Z",
        "run_manifest_sha256": "a" * 64,
        "transitions_sha256": "b" * 64,
        "evidence_manifest_sha256": "c" * 64,
        "formal_result_policy": "required_v1",
    }
    assert list(Draft202012Validator(schema).iter_errors(incomplete))


def test_legacy_policy_cannot_advance(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    manifest = _load(run_dir / "run_manifest.json")
    manifest["formal_result_policy"] = "legacy_read_only_v1"
    _write(run_dir / "run_manifest.json", manifest)
    with pytest.raises(ValueError, match="只允许历史验证"):
        advance_run(run_dir, "reviewer")
