"""候选版本、独立 Reviewer 与隔离输入包的回归测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_pipeline import (  # noqa: E402
    approved_supporting_review,
    create_paper_reader_workspace,
    current_candidate,
    record_paper_reader_review,
    record_reasonableness_review,
    record_technical_review,
    register_paper_candidate,
    require_approved_reasonableness_review,
)


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "run_manifest.json").write_text('{"run_id":"pipeline-test"}', encoding="utf-8")
    (run / "submission.pdf").write_bytes(b"pdf-v1")
    (run / "paper_claim_map.json").write_text('{"claims":[]}', encoding="utf-8")
    return run


def test_candidate_history_is_immutable_and_technical_review_binds_current_candidate(tmp_path: Path) -> None:
    """候选修订产生新 ID，技术审核不能指向旧 Candidate。"""
    run = _run(tmp_path)
    first = register_paper_candidate(
        run, ["submission.pdf", "paper_claim_map.json"], reason="首个候选稿", parent_candidate_id=None
    )
    assert first["candidate_id"] == "PC-0001"
    (run / "submission.pdf").write_bytes(b"pdf-v2")
    second = register_paper_candidate(
        run, ["submission.pdf", "paper_claim_map.json"], reason="修复表达", parent_candidate_id="PC-0001"
    )
    assert second["candidate_id"] == "PC-0002"
    assert (run / "paper_candidates" / "PC-0001" / "submission.pdf").read_bytes() == b"pdf-v1"
    assert current_candidate(run) == {"candidate_id": "PC-0002", "candidate_manifest_sha256": second["candidate_manifest_sha256"]}

    review = {
        "schema_version": "1.0.0", "artifact_type": "technical_review", "review_id": "TR-test0001",
        "run_id": "pipeline-test", "candidate_id": "PC-0002", "candidate_manifest_sha256": second["candidate_manifest_sha256"],
        "reviewed_at": "2026-07-16T12:00:00+00:00", "reviewer": {"type": "human", "identity": "tester", "session_id": None},
        "decision": "approved", "issues": [], "required_actions": [], "claim_restrictions": [], "required_limitations": [],
    }
    recorded = record_technical_review(run, review)
    assert recorded["attempt"] == 1
    review["candidate_id"] = "PC-0001"
    with pytest.raises(ValueError, match="当前 Candidate"):
        record_technical_review(run, review)


def test_reasonableness_review_blocks_until_approved(tmp_path: Path) -> None:
    """L3 审核失败留档但阻断进入论文阶段。"""
    run = _run(tmp_path)
    rejected = {
        "schema_version": "1.0.0", "artifact_type": "reasonableness_review", "review_id": "RR-test0001", "run_id": "pipeline-test",
        "reviewed_at": "2026-07-16T12:00:00+00:00", "reviewer": "tester", "decision": "needs_revision",
        "reason": "模型内最优不得被表述为现实世界的全局保证。", "claim_restrictions": [], "required_limitations": ["结论仅限模型假设"], "requested_revision_scope": "model_route",
    }
    record_reasonableness_review(run, rejected)
    with pytest.raises(ValueError, match="未批准"):
        require_approved_reasonableness_review(run)


def test_reasonableness_history_keeps_rejection_after_later_approval(tmp_path: Path) -> None:
    """后续批准不能覆盖前次合理性审核失败记录。"""
    run = _run(tmp_path)
    review = {
        "schema_version": "1.0.0", "artifact_type": "reasonableness_review", "review_id": "RR-history01", "run_id": "pipeline-test",
        "reviewed_at": "2026-07-16T12:00:00+00:00", "reviewer": "tester", "decision": "needs_revision",
        "reason": "候选筛选结果不能被写成最终决策，必须补充明确的结论边界。", "claim_restrictions": [], "required_limitations": [], "requested_revision_scope": "paper_candidate",
    }
    record_reasonableness_review(run, review)
    review.update({"review_id": "RR-history02", "decision": "approved", "requested_revision_scope": None})
    record_reasonableness_review(run, review)
    history = (run / "reasonableness_review_history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history) == 2
    approved = require_approved_reasonableness_review(run)
    assert approved["review_id"] == "RR-history02"


def test_declared_reader_review_cannot_satisfy_required_policy(tmp_path: Path) -> None:
    """没有物理执行证明的 declared_only Reader 只能用于调试。"""
    run = _run(tmp_path)
    candidate = register_paper_candidate(run, ["submission.pdf", "paper_claim_map.json"], reason="首稿")
    review = {
        "schema_version": "1.0.0", "artifact_type": "paper_reader_review", "review_id": "PRR-declared1", "run_id": "pipeline-test",
        "candidate_id": candidate["candidate_id"], "candidate_manifest_sha256": candidate["candidate_manifest_sha256"], "reviewed_at": "2026-07-16T12:00:00+00:00", "decision": "approved",
        "isolation": {"workspace_manifest_sha256": "a" * 64, "problem_sha256": "b" * 64, "submission_pdf_sha256": "c" * 64, "review_contract_sha256": "d" * 64, "review_prompt_sha256": "e" * 64, "repository_mounted": False, "parent_context_inherited": False, "network_access": False, "isolation_status": "declared_only", "reviewer_session_id": None},
        "answers": {"identified_model": "排名模型", "identified_purpose": "候选筛选", "reconstructed_mechanism_chain": ["输入数据", "输出排序"], "identified_result_role": "candidate_filter", "identified_claim_scope": "给定数据内"},
        "major_misunderstandings": [], "missing_explanations": [],
    }
    recorded = record_paper_reader_review(run, review)
    with pytest.raises(ValueError, match="workspace_enforced"):
        approved_supporting_review(
            run,
            {
                "path": recorded["path"],
                "sha256": recorded["sha256"],
                "candidate_id": candidate["candidate_id"],
                "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
            },
            kind="paper_reader",
            candidate=candidate,
            require_enforced=True,
        )


def test_reader_workspace_is_declared_only_without_os_sandbox(tmp_path: Path) -> None:
    """没有可验证 OS 沙箱时，不得伪装为 workspace_enforced。"""
    problem = tmp_path / "problem.pdf"; paper = tmp_path / "paper.pdf"
    problem.write_bytes(b"problem"); paper.write_bytes(b"paper")
    summary = create_paper_reader_workspace(tmp_path / "reader", problem_pdf=problem, submission_pdf=paper, review_contract={"version": 1}, prompt="review")
    assert summary["isolation_status"] == "declared_only"
    manifest = json.loads((tmp_path / "reader" / "workspace_manifest.json").read_text(encoding="utf-8"))
    assert manifest["repository_mounted"] is False
