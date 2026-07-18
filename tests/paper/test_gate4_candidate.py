from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from run_workflow import (  # noqa: E402
    FORMAL_IDENTITY_DEFAULTS,
    TRANSITION_VERSION,
    chain_transition_event,
    record_transition,
    replay_transition_log,
    verify_gate_artifacts,
)
from paper.gate4_candidate import (  # noqa: E402
    candidate_id_for_manifest,
    verify_candidate_manifest,
)
from test_repository_tooling import (  # noqa: E402
    _write_minimal_run_binding,
    _write_valid_gate_artifact,
)


def enable_paper_contract(run_dir: Path) -> None:
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["paper_pipeline_contract_version"] = "1.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def make_strict_gate4_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    enable_paper_contract(run_dir)
    (run_dir / "gate_artifacts").mkdir()
    for gate in (1, 3, 4):
        _write_valid_gate_artifact(run_dir, gate)
    return run_dir


def _candidate_binding(run_dir: Path) -> dict[str, str]:
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    runtime_manifest = json.loads(
        (run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8")
    )
    return {
        "run_id": str(run_manifest["run_id"]),
        "problem_id": str(run_manifest["problem_id"]),
        "profile": str(run_manifest["profile"]),
        "runtime_version": str(run_manifest["runtime_version"]),
        "runtime_pack_sha256": str(runtime_manifest["runtime_pack_sha256"]),
    }


def test_strict_gate4_accepts_only_hash_closed_passed_candidate(tmp_path: Path) -> None:
    run_dir = make_strict_gate4_run(tmp_path)

    manifest = verify_gate_artifacts(run_dir, 4)

    assert manifest["artifacts"][0]["role"] == "paper_candidate_manifest"
    assert json.loads((run_dir / "paper_candidate_manifest.json").read_text(encoding="utf-8"))[
        "candidate_status"
    ] == "paper_candidate_ready_for_independent_review"


def test_candidate_manifest_has_stable_non_self_referential_id(tmp_path: Path) -> None:
    run_dir = make_strict_gate4_run(tmp_path)
    manifest = json.loads((run_dir / "paper_candidate_manifest.json").read_text(encoding="utf-8"))
    candidate_id = str(manifest["candidate_id"])

    assert candidate_id.startswith("PC-")
    assert len(candidate_id) == 27
    assert candidate_id == candidate_id_for_manifest(_candidate_binding(run_dir), manifest["artifacts"])

    changed_artifacts = [dict(record) for record in manifest["artifacts"]]
    changed_artifacts[0]["sha256"] = "f" * 64
    assert candidate_id_for_manifest(_candidate_binding(run_dir), changed_artifacts) != candidate_id


def test_candidate_manifest_id_is_required_and_recomputed(tmp_path: Path) -> None:
    run_dir = make_strict_gate4_run(tmp_path)
    path = run_dir / "paper_candidate_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    binding = _candidate_binding(run_dir)

    manifest.pop("candidate_id")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_id"):
        verify_candidate_manifest(run_dir, binding)

    manifest["candidate_id"] = "PC-111111111111111111111111"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_id 与当前证据集合"):
        verify_candidate_manifest(run_dir, binding)


def test_gate4_candidate_cli_stages_existing_project_evidence(tmp_path: Path) -> None:
    run_dir = make_strict_gate4_run(tmp_path)
    (run_dir / "paper_candidate_manifest.json").unlink()
    arguments = [
        ("--external-precheck", "paper_external_precheck_report.json"),
        ("--suggested-repairs", "suggested_repairs.json"),
        ("--narrative-report", "paper_narrative_report.json"),
        ("--profile-snapshot", "paper_profile.snapshot.json"),
        ("--template-selection", "template_selection.json"),
        ("--template-manifest", "paper_template_manifest.json"),
        ("--render-attestation", "paper_render_attestation.json"),
        ("--humanization-report", "paper_humanization_report.json"),
        ("--verify-report", "paper_verify_report.json"),
        ("--claim-map", "paper_claim_map.json"),
        ("--model-consistency", "model_text_consistency_report.json"),
        ("--source-manifest", "paper_source_manifest.json"),
        ("--visual-review", "paper_visual_review.json"),
        ("--submission-pdf", "submission.pdf"),
    ]
    command = [
        sys.executable,
        str(ROOT / "scripts/paper/gate4_candidate.py"),
        "--run-dir",
        str(run_dir),
    ]
    for option, filename in arguments:
        command.extend([option, str(run_dir / filename)])

    completed = subprocess.run(command, capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
    assert "paper_candidate_ready_for_independent_review" in completed.stdout
    assert (run_dir / "paper_candidate_manifest.json").is_file()


@pytest.mark.parametrize(
    ("filename", "mutation", "message"),
    [
        (
            "paper_humanization_report.json",
            lambda payload: payload.update({"status": "failed"}),
            "paper_humanization_report",
        ),
        (
            "paper_verify_report.json",
            lambda payload: payload.update({"status": "failed"}),
            "paper_verify_report",
        ),
        (
            "paper_visual_review.json",
            lambda payload: payload.update({"status": "failed"}),
            "paper_visual_review",
        ),
        (
            "paper_narrative_report.json",
            lambda payload: payload.update(
                {"status": "failed", "submission_allowed": False}
            ),
            "paper_narrative_report",
        ),
    ],
)
def test_strict_gate4_rejects_failed_evidence(
    tmp_path: Path, filename: str, mutation: object, message: str
) -> None:
    run_dir = make_strict_gate4_run(tmp_path)
    path = run_dir / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)  # type: ignore[operator]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        verify_gate_artifacts(run_dir, 4)


def test_strict_gate4_rejects_submission_pdf_tampering(tmp_path: Path) -> None:
    run_dir = make_strict_gate4_run(tmp_path)
    (run_dir / "submission.pdf").write_bytes(b"%PDF-1.4\ntampered\n%%EOF\n")

    with pytest.raises(ValueError, match="内容哈希或大小不匹配"):
        verify_gate_artifacts(run_dir, 4)


def test_gate4_transition_uses_candidate_ready_state_and_gate5_remains_separate(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    enable_paper_contract(run_dir)
    (run_dir / "gate_artifacts").mkdir()
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    initialized = chain_transition_event(
        {
            "transition_version": TRANSITION_VERSION,
            "from": None,
            "to": None,
            "completed_gate": None,
            "next_gate": 0,
            "state": "initialized",
            "material_ready": True,
            "max_gate": 5,
            **{
                field: run_manifest[field]
                for field in FORMAL_IDENTITY_DEFAULTS | {"run_id": "", "problem_id": "", "profile": "", "runtime_version": "", "runtime_pack_sha256": ""}
            },
        },
        None,
    )
    (run_dir / "transitions.jsonl").write_text(json.dumps(initialized) + "\n", encoding="utf-8")
    record_transition(run_dir, None, 0, "human", "approved")
    for gate in range(5):
        _write_valid_gate_artifact(run_dir, gate)
        record_transition(run_dir, gate, gate + 1, "human", "approved")

    last = json.loads((run_dir / "transitions.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["state"] == "paper_candidate_ready_for_independent_review"
    state = replay_transition_log(run_dir)
    assert state["current_gate"] == 5
    assert state["completed"] is False


def test_legacy_run_without_contract_keeps_historical_gate4_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "legacy"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    (run_dir / "gate_artifacts").mkdir()
    for gate in (1, 3, 4):
        _write_valid_gate_artifact(run_dir, gate)

    manifest = verify_gate_artifacts(run_dir, 4)

    assert manifest["artifacts"][0]["role"] == "paper_claim_map"
    assert not (run_dir / "paper_candidate_manifest.json").exists()
