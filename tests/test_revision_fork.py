"""受控修订 Run 的事务与谱系回归测试。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_workflow  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_child_factory(args):
    child = Path(args.output_root) / args.run_id
    child.mkdir(parents=True)
    (child / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": args.run_id,
                "workflow": args.workflow,
                "problem_id": args.problem,
                "profile": args.profile,
                "runtime_version": "0.1.0",
                "runtime_pack_sha256": "a" * 64,
                "materials": args.materials,
                **run_workflow.FORMAL_IDENTITY_DEFAULTS,
            }
        ),
        encoding="utf-8",
    )
    run_workflow._init_transitions(child, "0-5", True)
    return child, True


def test_revision_fork_supersedes_parent_only_after_child_is_committed(tmp_path: Path, monkeypatch) -> None:
    """修订不回退 Gate，父子 Run 与事务记录必须相互绑定。"""
    parent = tmp_path / "parent-run"
    parent.mkdir()
    parent_manifest = {
        "run_id": "parent-run",
        "workflow": "full_replay",
        "problem_id": "2021-C",
        "profile": "engineering_optimization",
        "runtime_version": "0.1.0",
        "runtime_pack_sha256": "a" * 64,
        "materials": "materials",
        "gates": "0-5",
        "mode": "standard",
        "runtime_manifest_version": "1.2.0",
        **run_workflow.FORMAL_IDENTITY_DEFAULTS,
    }
    (parent / "run_manifest.json").write_text(json.dumps(parent_manifest), encoding="utf-8")
    run_workflow._init_transitions(parent, "0-5", True)
    run_workflow.record_transition(parent, None, 0, "starter", "approved")

    monkeypatch.setattr(run_workflow, "create_full_replay_run", _fake_child_factory)
    monkeypatch.setattr(run_workflow, "_verified_material_digest", lambda _manifest: "b" * 64)
    monkeypatch.setattr(run_workflow, "build_run_evidence_manifest", lambda _run, _run_id: {"artifacts": []})

    result = run_workflow.fork_revision_run(
        parent,
        revision_scope="model_route",
        reviewer="reasonableness-reviewer",
        reason="模型角色与题意不一致，必须从 Gate 0 重建。",
        transaction_id="revisiontx1",
    )

    child = Path(result["child_run"])
    assert result["status"] == "committed"
    assert run_workflow.replay_transition_log(parent)["lifecycle_status"] == "superseded"
    assert json.loads((child / "revision_fork_record.json").read_text(encoding="utf-8"))["status"] == "committed"
    assert run_workflow._fork_lineage_errors(parent, run_workflow.replay_transition_log(parent)) == []
    assert run_workflow._fork_lineage_errors(child, run_workflow.replay_transition_log(child)) == []


def test_revision_fork_recovers_from_post_seal_gate_drift(tmp_path: Path, monkeypatch) -> None:
    """原 Run 继续 fail-closed，但合法 revision 可绑定有效前缀并重新冻结。"""
    parent = tmp_path / "parent-run"
    parent.mkdir()
    parent_manifest = {
        "run_id": "parent-run",
        "workflow": "full_replay",
        "problem_id": "2025-C",
        "profile": "prediction",
        "runtime_version": "0.1.0",
        "runtime_pack_sha256": "a" * 64,
        "materials": "materials",
        "gates": "0-5",
        "mode": "strict",
        "runtime_manifest_version": "1.3.0",
        **run_workflow.FORMAL_IDENTITY_DEFAULTS,
    }
    (parent / "run_manifest.json").write_text(json.dumps(parent_manifest), encoding="utf-8")
    gate_dir = parent / "gate_artifacts"
    gate_dir.mkdir()
    for gate in range(3):
        (gate_dir / f"gate_{gate}.manifest.json").write_text(
            json.dumps({"gate": gate, "sealed": True}), encoding="utf-8"
        )
    (parent / "execution_spec.json").write_text("post-seal mutation", encoding="utf-8")
    run_workflow._init_transitions(parent, "0-5", True)

    monkeypatch.setattr(run_workflow, "verify_gate_artifacts", lambda _run, _gate: None)
    run_workflow.record_transition(parent, None, 0, "operator", "approved")
    run_workflow.record_transition(parent, 0, 1, "operator", "approved")
    run_workflow.record_transition(parent, 1, 2, "operator", "approved")
    run_workflow.record_transition(parent, 2, 3, "operator", "approved")

    def fail_drifted_gate(_run: Path, gate: int):
        if gate == 2:
            raise ValueError("Gate 2 产物 execution_spec.json SHA-256 不匹配")
        return None

    monkeypatch.setattr(run_workflow, "verify_gate_artifacts", fail_drifted_gate)
    monkeypatch.setattr(run_workflow, "create_full_replay_run", _fake_child_factory)
    monkeypatch.setattr(run_workflow, "_verified_material_digest", lambda _manifest: "b" * 64)
    monkeypatch.setattr(run_workflow, "build_run_evidence_manifest", lambda _run, _run_id: {"artifacts": []})

    with pytest.raises(ValueError, match="Gate 2 产物"):
        run_workflow.replay_transition_log(parent)

    protected_before = {
        path.relative_to(parent).as_posix(): _sha256(path)
        for path in parent.rglob("*")
        if path.is_file() and path.name != "transitions.jsonl"
    }
    result = run_workflow.fork_revision_run(
        parent,
        revision_scope="formal_result",
        reviewer="ai_workflow_operator",
        reason="Gate 2 封存后 execution_spec 漂移，必须在新 Run 重新生成 Gate 2。",
        transaction_id="integrityrevision1",
    )
    child = Path(result["child_run"])
    protected_after = {
        path.relative_to(parent).as_posix(): _sha256(path)
        for path in parent.rglob("*")
        if path.is_file() and path.name != "transitions.jsonl"
    }

    assert protected_after == protected_before
    assert run_workflow.replay_transition_log(parent, verify_artifacts=False)["lifecycle_status"] == "superseded"
    record = json.loads((child / "revision_fork_record.json").read_text(encoding="utf-8"))
    assert [item["gate"] for item in record["parent_gate_artifact_refs"]] == [0, 1]
    assert record["parent_integrity_failure"]["failed_gate"] == 2
    assert record["parent_integrity_failure"]["status"] == "blocked_integrity_mismatch"
    child_manifest = json.loads((child / "run_manifest.json").read_text(encoding="utf-8"))
    assert child_manifest["revision_parent_run_id"] == parent.name
    assert child_manifest["problem_id"] == parent_manifest["problem_id"]
    assert child_manifest["profile"] == parent_manifest["profile"]
    assert child_manifest["inherited_material_sha256"] == "b" * 64
    assert not (child / "gate_artifacts" / "gate_2.manifest.json").exists()
    with pytest.raises(ValueError, match="Gate 2 产物"):
        run_workflow.replay_transition_log(parent)
    with pytest.raises(ValueError, match="active"):
        run_workflow.fork_revision_run(
            parent,
            revision_scope="formal_result",
            reviewer="ai_workflow_operator",
            reason="禁止同一 parent 创建第二个活跃 revision。",
            transaction_id="integrityrevision2",
        )


def test_revision_fork_resumes_after_child_publish_interruption(tmp_path: Path, monkeypatch) -> None:
    """子 Run 发布后中断时，固定 transaction ID 必须可恢复且不产生第二个子 Run。"""
    parent = tmp_path / "parent-run"
    parent.mkdir()
    manifest = {
        "run_id": "parent-run",
        "workflow": "full_replay",
        "problem_id": "2025-C",
        "profile": "prediction",
        "runtime_version": "0.1.0",
        "runtime_pack_sha256": "a" * 64,
        "materials": "materials",
        "gates": "0-5",
        "mode": "strict",
        "runtime_manifest_version": "1.3.0",
        **run_workflow.FORMAL_IDENTITY_DEFAULTS,
    }
    (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    run_workflow._init_transitions(parent, "0-5", True)
    run_workflow.record_transition(parent, None, 0, "operator", "approved")
    monkeypatch.setattr(run_workflow, "create_full_replay_run", _fake_child_factory)
    monkeypatch.setattr(run_workflow, "_verified_material_digest", lambda _manifest: "b" * 64)
    monkeypatch.setattr(run_workflow, "build_run_evidence_manifest", lambda _run, _run_id: {"artifacts": []})

    original_append = run_workflow._append_revision_fork_event

    def interrupt_once(_parent: Path, _transaction):
        raise RuntimeError("simulated interruption after child publish")

    monkeypatch.setattr(run_workflow, "_append_revision_fork_event", interrupt_once)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        run_workflow.fork_revision_run(
            parent,
            revision_scope="diagnosis",
            reviewer="ai_workflow_operator",
            reason="验证 revision 事务可恢复。",
            transaction_id="resumerevision1",
        )

    transaction_path = tmp_path / ".transactions/fork-revision/resumerevision1.json"
    interrupted = json.loads(transaction_path.read_text(encoding="utf-8"))
    assert interrupted["status"] == "child_published"
    child_id = interrupted["child_run_id"]

    monkeypatch.setattr(run_workflow, "_append_revision_fork_event", original_append)
    resumed = run_workflow.fork_revision_run(
        parent,
        revision_scope="diagnosis",
        reviewer="ai_workflow_operator",
        reason="验证 revision 事务可恢复。",
        transaction_id="resumerevision1",
        resume=True,
    )
    assert resumed["status"] == "committed"
    assert Path(resumed["child_run"]).name == child_id
    assert run_workflow.replay_transition_log(parent)["lifecycle_status"] == "superseded"
