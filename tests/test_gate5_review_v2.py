"""Gate 5 v2 审核账本与失败闭环回归测试。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_workflow  # noqa: E402
from review_ledger import append_immutable_review, reconcile_orphan_reviews, verify_history  # noqa: E402
from review_pipeline import record_technical_review, register_paper_candidate  # noqa: E402


def _validate_ledger_review(review: dict[str, Any]) -> None:
    """为通用账本提供最小审核合同，专测不可变记录语义。"""
    if not isinstance(review.get("review_id"), str):
        raise ValueError("review_id 缺失")
    if not isinstance(review.get("attempt"), int) or review["attempt"] < 1:
        raise ValueError("attempt 非法")
    if review.get("decision") not in {"approved", "needs_revision", "rejected"}:
        raise ValueError("decision 非法")
    if not isinstance(review.get("reviewed_at"), str):
        raise ValueError("reviewed_at 缺失")


def _ledger_review(review_id: str, decision: str = "needs_revision") -> dict[str, Any]:
    return {
        "review_id": review_id,
        "attempt": 999,
        "decision": decision,
        "reviewed_at": "2026-07-16T12:00:00+08:00",
        "candidate_id": "LEGACY-PC-test",
        "candidate_manifest_sha256": "a" * 64,
        "review_type": "final_decision",
    }


def test_review_ledger_preserves_attempts_and_detects_tampering(tmp_path: Path) -> None:
    """历史事件按写锁顺序编号，且任一既有事件修改都会破坏哈希链。"""
    first = append_immutable_review(
        tmp_path,
        _ledger_review("G5R-ledger-a"),
        review_directory="reviews/gate5",
        history_filename="gate_5_review_history.jsonl",
        validate_review=_validate_ledger_review,
    )
    second = append_immutable_review(
        tmp_path,
        _ledger_review("G5R-ledger-b", "approved"),
        review_directory="reviews/gate5",
        history_filename="gate_5_review_history.jsonl",
        validate_review=_validate_ledger_review,
    )

    assert first["attempt"] == 1
    assert second["attempt"] == 2
    entries, head = verify_history(tmp_path, "gate_5_review_history.jsonl")
    assert [entry["review_id"] for entry in entries] == ["G5R-ledger-a", "G5R-ledger-b"]
    assert head == entries[-1]["event_sha256"]

    history_path = tmp_path / "gate_5_review_history.jsonl"
    tampered = json.loads(history_path.read_text(encoding="utf-8").splitlines()[0])
    tampered["decision"] = "rejected"
    history_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="event_sha256"):
        verify_history(tmp_path, "gate_5_review_history.jsonl")


def test_orphan_review_requires_matching_unique_identifier(tmp_path: Path) -> None:
    """恢复不得把错误文件名或重复 ID 的孤立文件写入 history。"""
    append_immutable_review(
        tmp_path,
        _ledger_review("G5R-existing"),
        review_directory="reviews/gate5",
        history_filename="gate_5_review_history.jsonl",
        validate_review=_validate_ledger_review,
    )
    orphan = _ledger_review("G5R-existing")
    orphan["attempt"] = 2
    wrong_path = tmp_path / "reviews" / "gate5" / "G5R-other.json"
    wrong_path.write_text(json.dumps(orphan), encoding="utf-8")

    with pytest.raises(ValueError, match="文件名必须与 review_id 一致"):
        reconcile_orphan_reviews(
            tmp_path,
            review_directory="reviews/gate5",
            history_filename="gate_5_review_history.jsonl",
            validate_review=_validate_ledger_review,
        )


def _write_v2_review_fixture(run_dir: Path) -> dict[str, Any]:
    """构造只供 Gate 5 审核合同校验使用的最小运行现场。"""
    run_dir.mkdir()
    runtime_pack = b"gate five v2 fixture"
    runtime_sha = hashlib.sha256(runtime_pack).hexdigest()
    (run_dir / "runtime_pack.md").write_bytes(runtime_pack)
    (run_dir / "runtime_pack.manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "1.2.0",
                "profile": "engineering_optimization",
                "runtime_version": "0.1.0",
                "runtime_pack_sha256": runtime_sha,
                "workflow_context": "full_replay",
                "runtime_contract": {
                    "path": "runtime_contracts/full_replay.md",
                    "sha256": hashlib.sha256(
                        (ROOT / "runtime_contracts" / "full_replay.md").read_bytes()
                    ).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "g5-v2-test",
                "workflow": "full_replay",
                "problem_id": "2024-C",
                "profile": "engineering_optimization",
                "runtime_version": "0.1.0",
                "runtime_pack_sha256": runtime_sha,
                "gate_5_review_contract_version": "2.0.0",
                "gate_5_policy_version": "recording_only_v1",
            }
        ),
        encoding="utf-8",
    )
    gate_4_manifest = run_dir / "gate_artifacts" / "gate_4.manifest.json"
    gate_4_manifest.parent.mkdir()
    gate_4_manifest.write_text('{"gate": 4}\n', encoding="utf-8")
    candidate_sha = hashlib.sha256(gate_4_manifest.read_bytes()).hexdigest()
    checklist = {
        name: {"status": "passed", "reason": "审核通过", "evidence_refs": []}
        for name in run_workflow.GATE_5_CHECKLIST_KEYS
    }
    return {
        "schema_version": "2.0.0",
        "artifact_type": "gate_5_review",
        "review_id": "G5R-fixture1",
        "review_type": "final_decision",
        "policy_version": "recording_only_v1",
        "attempt": 1,
        "run_id": "g5-v2-test",
        "problem_id": "2024-C",
        "profile": "engineering_optimization",
        "runtime_version": "0.1.0",
        "runtime_pack_sha256": runtime_sha,
        "candidate_id": f"LEGACY-PC-{candidate_sha}",
        "candidate_manifest_sha256": candidate_sha,
        "candidate_binding_version": "fixed_gate4_v1",
        "reviewer": {"type": "human", "identity": "tester", "session_id": None},
        "reviewed_at": "2026-07-16T12:00:00+08:00",
        "decision": "approved",
        "reason": "所有可验证的审核条件均已满足，可以完成当前运行。",
        "checklist": checklist,
        "issues": [],
        "required_actions": [],
        "claim_restrictions": [],
        "required_limitations": [],
        "restriction_closure_refs": [],
        "requested_revision_scope": None,
        "supporting_reviews": [],
    }


def test_recording_only_review_rejects_unverifiable_restrictions(tmp_path: Path) -> None:
    """候选版本化前，限制性通过不能假装已经完成证据闭合。"""
    review = _write_v2_review_fixture(tmp_path / "run")
    review["claim_restrictions"] = ["不得将模型内结论表述为现实保证"]
    review["restriction_closure_refs"] = [
        {"path": "gate_artifacts/gate_4.manifest.json", "sha256": review["candidate_manifest_sha256"]}
    ]

    with pytest.raises(ValueError, match="暂不允许 approved"):
        run_workflow._validate_gate_5_v2_review(tmp_path / "run", review)


def test_technical_required_policy_accepts_only_current_candidate_review(tmp_path: Path) -> None:
    """最终 Gate 5 批准必须聚合当前 Candidate 的 approved Technical Review。"""
    run_dir = tmp_path / "run"
    review = _write_v2_review_fixture(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["gate_5_policy_version"] = "technical_required_v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "submission.pdf").write_bytes(b"paper")
    (run_dir / "paper_claim_map.json").write_text('{"claims":[]}', encoding="utf-8")
    candidate = register_paper_candidate(run_dir, ["submission.pdf", "paper_claim_map.json"], reason="首个版本化候选")
    technical = {
        "schema_version": "1.0.0", "artifact_type": "technical_review", "review_id": "TR-current01", "attempt": 1,
        "run_id": "g5-v2-test", "candidate_id": candidate["candidate_id"], "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
        "reviewed_at": "2026-07-16T12:00:00+08:00", "reviewer": {"type": "human", "identity": "tester", "session_id": None},
        "decision": "approved", "issues": [], "required_actions": [], "claim_restrictions": [], "required_limitations": [],
    }
    recorded = record_technical_review(run_dir, technical)
    review.update(
        {
            "policy_version": "technical_required_v1",
            "candidate_id": candidate["candidate_id"],
            "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
            "candidate_binding_version": "versioned_candidate_v2",
            "supporting_reviews": [{
                "review_id": technical["review_id"], "path": recorded["path"], "sha256": recorded["sha256"], "decision": "approved",
                "candidate_id": candidate["candidate_id"], "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
            }],
        }
    )
    run_workflow._validate_gate_5_v2_review(run_dir, review)

    review["supporting_reviews"][0]["candidate_id"] = "PC-0000"
    with pytest.raises(ValueError, match="Candidate 不一致"):
        run_workflow._validate_gate_5_v2_review(run_dir, review)


def test_human_final_policy_allows_ai_precheck_but_requires_human_gate5(tmp_path: Path) -> None:
    """AI 可留下技术预审，但最终批准必须由人工作出。"""
    run_dir = tmp_path / "run"
    review = _write_v2_review_fixture(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["gate_5_policy_version"] = "human_final_technical_required_v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "submission.pdf").write_bytes(b"paper")
    (run_dir / "paper_claim_map.json").write_text('{"claims":[]}', encoding="utf-8")
    candidate = register_paper_candidate(run_dir, ["submission.pdf", "paper_claim_map.json"], reason="首个候选")
    technical = {
        "schema_version": "1.0.0", "artifact_type": "technical_review", "review_id": "TR-ai-precheck", "attempt": 1,
        "run_id": "g5-v2-test", "candidate_id": candidate["candidate_id"], "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
        "reviewed_at": "2026-07-16T12:00:00+08:00", "reviewer": {"type": "ai_assistant", "identity": "codex-review", "session_id": "session-001"},
        "decision": "approved", "issues": [], "required_actions": [], "claim_restrictions": [], "required_limitations": [],
    }
    recorded = record_technical_review(run_dir, technical)
    review.update({
        "policy_version": "human_final_technical_required_v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
        "candidate_binding_version": "versioned_candidate_v2",
        "supporting_reviews": [{"review_id": technical["review_id"], "path": recorded["path"], "sha256": recorded["sha256"], "decision": "approved", "candidate_id": candidate["candidate_id"], "candidate_manifest_sha256": candidate["candidate_manifest_sha256"]}],
    })
    run_workflow._validate_gate_5_v2_review(run_dir, review)
    transitions_before = (run_dir / "transitions.jsonl").read_bytes() if (run_dir / "transitions.jsonl").is_file() else None
    handoff = run_workflow.prepare_human_final_review_handoff(run_dir)
    assert handoff["reused"] is False
    handoff_dir = run_dir / handoff["handoff_dir"]
    dossier = (run_dir / handoff["dossier"]).read_text(encoding="utf-8")
    template = json.loads((run_dir / handoff["template"]).read_text(encoding="utf-8"))
    handoff_manifest = json.loads((run_dir / handoff["manifest"]).read_text(encoding="utf-8"))
    assert candidate["candidate_id"] in dossier
    assert recorded["sha256"] in dossier
    assert template["candidate_id"] == candidate["candidate_id"]
    assert template["supporting_reviews"] == [{
        "review_id": technical["review_id"], "path": recorded["path"], "sha256": recorded["sha256"],
        "decision": "approved", "candidate_id": candidate["candidate_id"],
        "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
    }]
    assert template["_template_notice"]
    assert handoff_manifest["status"] == "pending_human_final_decision"
    with pytest.raises(ValueError, match="不符合 Schema"):
        run_workflow._validate_gate_5_v2_review(run_dir, template)
    assert not (run_dir / "gate_5_review_history.jsonl").exists()
    assert not (run_dir / "seal_record.json").exists()
    if transitions_before is None:
        assert not (run_dir / "transitions.jsonl").exists()
    else:
        assert (run_dir / "transitions.jsonl").read_bytes() == transitions_before
    assert run_workflow.prepare_human_final_review_handoff(run_dir)["reused"] is True
    assert handoff_dir.is_dir()
    review["reviewer"]["type"] = "independent_llm"
    with pytest.raises(ValueError, match="必须由人工决策"):
        run_workflow._validate_gate_5_v2_review(run_dir, review)


def test_handoff_rejects_latest_technical_review_that_needs_revision(tmp_path: Path) -> None:
    """技术审核产生新问题后，旧的 approved 结论不得继续送交人工终审。"""
    run_dir = tmp_path / "run"
    review = _write_v2_review_fixture(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["gate_5_policy_version"] = "human_final_technical_required_v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "submission.pdf").write_bytes(b"paper")
    (run_dir / "paper_claim_map.json").write_text('{"claims":[]}', encoding="utf-8")
    candidate = register_paper_candidate(run_dir, ["submission.pdf", "paper_claim_map.json"], reason="首个候选")
    common = {
        "schema_version": "1.0.0", "artifact_type": "technical_review",
        "run_id": "g5-v2-test", "candidate_id": candidate["candidate_id"],
        "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
        "reviewed_at": "2026-07-16T12:00:00+08:00",
        "reviewer": {"type": "ai_assistant", "identity": "codex-review", "session_id": "session-001"},
        "issues": [], "required_actions": [], "claim_restrictions": [], "required_limitations": [],
    }
    record_technical_review(run_dir, {**common, "review_id": "TR-approved-first", "attempt": 1, "decision": "approved"})
    record_technical_review(run_dir, {
        **common,
        "review_id": "TR-needs-revision",
        "attempt": 2,
        "decision": "needs_revision",
        "issues": [{"issue_id": "TI-1", "severity": "major", "description": "需要修订证据说明"}],
        "required_actions": ["补充证据说明并产生新 Candidate"],
    })

    with pytest.raises(ValueError, match="最新 Technical Review 未通过"):
        run_workflow.prepare_human_final_review_handoff(run_dir)
