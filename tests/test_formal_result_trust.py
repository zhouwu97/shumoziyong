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
from formal_result.verifier import verify_formal_result_bundle
from formal_result_fixtures import write_formal_result_bundle
from run_workflow import advance_run, create_new_problem_run
from test_repository_tooling import _v2_gate_0_run, _write_material_manifest


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


def test_canonicalization_separates_semantics_from_format_and_preserves_array_order() -> None:
    left = {"b": 1.0, "a": [{"x": 1}, {"x": 2}]}
    same = {"a": [{"x": 1}, {"x": 2}], "b": 1.0000000001}
    reordered = {"a": [{"x": 2}, {"x": 1}], "b": 1.0}
    assert canonical_bytes(left) == canonical_bytes(same)
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


def test_required_bundle_rejects_hardlinked_core_file(tmp_path: Path) -> None:
    run_dir, envelope = _bundle(tmp_path)
    decision_path = envelope.parent / "decision_variables.json"
    external_path = tmp_path / "external_decision_variables.json"
    external_path.write_bytes(decision_path.read_bytes())
    decision_path.unlink()
    os.link(external_path, decision_path)

    with pytest.raises(FormalResultVerificationError, match="禁止 hardlink"):
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


def test_legacy_policy_cannot_advance(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    manifest = _load(run_dir / "run_manifest.json")
    manifest["formal_result_policy"] = "legacy_read_only_v1"
    _write(run_dir / "run_manifest.json", manifest)
    with pytest.raises(ValueError, match="只允许历史验证"):
        advance_run(run_dir, "reviewer")
