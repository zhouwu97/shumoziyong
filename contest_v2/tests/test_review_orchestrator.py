from __future__ import annotations

import json
from pathlib import Path

import pytest

from contest_v2.review_orchestrator import (
    check_stage_gate,
    collect,
    load_request,
    dispatch,
    prepare_request,
    prepare_rereview,
)


class FakeAdapter:
    def __init__(self, *, decision: str = "SUBMISSION_RECOMMENDED", fail_create: bool = False, fail_result: bool = False) -> None:
        self.decision = decision
        self.fail_create = fail_create
        self.fail_result = fail_result

    def create(self, request: dict) -> dict:
        if self.fail_create:
            raise RuntimeError("create unavailable")
        return {"task_id": f"task-{request['request_id']}", "provider": "fake"}

    def result(self, task_id: str) -> dict:
        if self.fail_result:
            raise RuntimeError("result unavailable")
        return {"task_id": task_id, "conclusion": self.decision, "must_fix": []}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_ready_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    write_json(run / "verify_report.json", {"status": "passed"})
    write_json(run / "review" / "paper_admission.json", {"paper_admission": "pass", "paper_type": "submission_candidate"})
    write_json(run / "contest.json", {"question_ids": ["q1"]})
    write_json(run / "questions" / "q1" / "question.json", {"id": "q1"})
    (run / "questions" / "q1" / "results").mkdir(parents=True)
    (run / "questions" / "q1" / "results" / "result.json").write_text("{}", encoding="utf-8")
    (run / "paper" / "main.typ").parent.mkdir(parents=True)
    (run / "paper" / "main.typ").write_text("#set page()", encoding="utf-8")
    (run / "questions" / "q1" / "paper.typ").write_text("= 问题一\n", encoding="utf-8")
    (run / "result_ledger.json").write_text("{}", encoding="utf-8")
    (run / "paper" / "submission.pdf").write_bytes(b"%PDF fake")
    (run / "package").mkdir()
    (run / "package" / "submission.pdf").write_bytes(b"%PDF fake")
    (run / "package" / "support.zip").write_bytes(b"zip")
    reports = {
        "MODEL_REVIEW.md": "MODEL_REVIEW: READY\n",
        "EXPERIMENT_REVIEW.md": "EXPERIMENT_REVIEW: PASS\n",
        "PAPER_COHERENCE_REVIEW.md": "PAPER_COHERENCE_REVIEW: READY\n",
        "FORMAT_SUBMISSION_REVIEW.md": "FORMAT_SUBMISSION_REVIEW: READY\n",
    }
    for name, body in reports.items():
        (run / "reports" / name).parent.mkdir(parents=True, exist_ok=True)
        (run / "reports" / name).write_text(body, encoding="utf-8")
    return run


def test_stage_gate_requires_real_phase_outputs(tmp_path: Path) -> None:
    run = make_ready_run(tmp_path)
    assert check_stage_gate(run, "R4")["status"] == "READY"
    (run / "package" / "support.zip").unlink()
    gate = check_stage_gate(run, "R4")
    assert gate["status"] == "BLOCKED"
    assert any("support.zip" in item for item in gate["blockers"])


def test_r5_requires_all_stage_gates(tmp_path: Path) -> None:
    run = make_ready_run(tmp_path)
    request = prepare_request(run)
    assert request["status"] == "REQUEST_READY"
    assert (run / "review" / "review_request.json").is_file()


def test_dispatch_without_adapter_is_honest(tmp_path: Path) -> None:
    run = make_ready_run(tmp_path)
    prepare_request(run)
    request = dispatch(run)
    assert request["status"] == "REQUEST_READY"
    assert request["task_id"] is None
    assert request["failure"]["code"] == "adapter_not_configured"


def test_create_collect_and_rereview_are_distinct(tmp_path: Path) -> None:
    run = make_ready_run(tmp_path)
    first = prepare_request(run)
    created = dispatch(run, FakeAdapter())
    assert created["status"] == "CREATED"
    assert created["task_id"]
    received = collect(run, FakeAdapter())
    assert received["status"] == "REVIEW_RECOMMENDED"

    # 复审只能从需要修补的结论产生，并且 request_id/task_id 不复用。
    run2 = make_ready_run(tmp_path / "repair")
    prepare_request(run2)
    dispatch(run2, FakeAdapter())
    collect(run2, FakeAdapter(decision="MAJOR_REVISION"))
    previous = load_request(run2)
    repaired = prepare_rereview(run2)
    assert repaired["round"] == 2
    assert repaired["parent_request_id"] == previous["request_id"]
    assert repaired["request_id"] != previous["request_id"]


def test_adapter_failures_are_persisted(tmp_path: Path) -> None:
    run = make_ready_run(tmp_path)
    prepare_request(run)
    failed_create = dispatch(run, FakeAdapter(fail_create=True))
    assert failed_create["status"] == "CREATION_FAILED"
    assert failed_create["failure"]["code"] == "adapter_create_failed"

    run2 = make_ready_run(tmp_path / "result")
    prepare_request(run2)
    dispatch(run2, FakeAdapter())
    failed_result = collect(run2, FakeAdapter(fail_result=True))
    assert failed_result["status"] == "RESULT_FAILED"
    assert failed_result["failure"]["code"] == "adapter_result_failed"


def test_r5_rejects_unfinished_r1(tmp_path: Path) -> None:
    run = make_ready_run(tmp_path)
    (run / "reports" / "MODEL_REVIEW.md").write_text("MODEL_REVIEW: REVISE\n", encoding="utf-8")
    with pytest.raises(ValueError, match="R1-R4 尚未全部通过"):
        prepare_request(run)
