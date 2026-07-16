"""受控修订 Run 的事务与谱系回归测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_workflow  # noqa: E402


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

    def fake_create(args):
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

    monkeypatch.setattr(run_workflow, "create_full_replay_run", fake_create)
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
