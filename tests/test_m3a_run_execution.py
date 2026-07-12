"""M3A Run 专属 Sandboxie 执行证明与攻击回归。"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.errors import FormalResultVerificationError
from formal_result.run_execution_attestation import verify_run_execution_attestation
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
    with pytest.raises(FormalResultVerificationError, match="Output Manifest"):
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
