"""R5 独立 Reviewer 编排状态机。

本模块只定义可复现的请求、任务和结果生命周期。Codex 对话创建属于外部
adapter；adapter 未配置时请求会停在 REQUEST_READY，而不会伪造 task_id。
"""

from __future__ import annotations

import json
import shlex
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


REQUEST_PATH = Path("review/review_request.json")
R5_STATUSES = {
    "REQUEST_READY",
    "CREATION_PENDING",
    "CREATED",
    "RESULT_PENDING",
    "REVIEW_RECEIVED",
    "CREATION_FAILED",
    "RESULT_FAILED",
    "REVIEW_NEEDS_REPAIR",
    "REVIEW_RECOMMENDED",
}
REVIEW_DECISIONS = {"SUBMISSION_RECOMMENDED", "MAJOR_REVISION", "NOT_RECOMMENDED"}
STAGE_FILES = {
    "MODEL_REVIEW.md": {"DRAFT", "READY", "REVISE", "BLOCKED"},
    "EXPERIMENT_REVIEW.md": {"PENDING", "PASS", "REVISE", "BLOCKED"},
    "PAPER_COHERENCE_REVIEW.md": {"PENDING", "READY", "REVISE", "BLOCKED"},
    "FORMAT_SUBMISSION_REVIEW.md": {"PENDING", "READY", "REVISE", "BLOCKED"},
}
STAGE_ORDER = ("R1", "R2", "R3", "R4")
STAGE_REPORTS = {
    "R1": ("MODEL_REVIEW.md", "READY"),
    "R2": ("EXPERIMENT_REVIEW.md", "PASS"),
    "R3": ("PAPER_COHERENCE_REVIEW.md", "READY"),
    "R4": ("FORMAT_SUBMISSION_REVIEW.md", "READY"),
}


class ReviewerAdapter(Protocol):
    """外部 AI 对话系统的最小适配器合同。"""

    def create(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def result(self, task_id: str) -> Mapping[str, Any]: ...


class CommandReviewerAdapter:
    """通过外部命令连接 Codex/其他 Reviewer 服务。

    命令合同：``<command> create`` 从 stdin 读取请求 JSON，输出至少含 task_id
    的 JSON；``<command> result`` 从 stdin 读取 task_id JSON，输出 Reviewer 结果。
    """

    def __init__(self, command: Sequence[str] | str, *, timeout_seconds: int = 120) -> None:
        self.command = shlex.split(command, posix=False) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("Reviewer adapter command 不能为空")
        self.timeout_seconds = timeout_seconds

    def _run(self, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            self.command + [action],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"Reviewer adapter {action} 失败")
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Reviewer adapter {action} 未返回 JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Reviewer adapter {action} 返回值必须是 JSON 对象")
        return value

    def create(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._run("create", request)

    def result(self, task_id: str) -> Mapping[str, Any]:
        return self._run("result", {"task_id": task_id})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 顶层必须是 JSON 对象")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stage_status(path: Path, allowed: set[str]) -> str:
    if not path.is_file():
        raise ValueError(f"缺少阶段审核文件：{path}")
    first = path.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    if not first:
        raise ValueError(f"阶段审核文件为空：{path}")
    marker = first[0].split(":", 1)[-1].strip()
    if marker not in allowed:
        raise ValueError(f"{path.name} 状态无效：{marker}")
    return marker


def _assert_ready(run_dir: Path) -> dict[str, str]:
    r4_gate = check_stage_gate(run_dir, "R4")
    if r4_gate["status"] != "READY":
        raise ValueError(f"R1-R4 阶段顺序或产物未满足：{r4_gate['blockers']}")
    verify_path = run_dir / "verify_report.json"
    if not verify_path.is_file() or _read(verify_path).get("status") != "passed":
        raise ValueError("工程验收未通过，不能创建 R5 Reviewer 请求")
    admission_path = run_dir / "review/paper_admission.json"
    if not admission_path.is_file():
        raise ValueError("缺少 Paper Admission，不能创建 R5 Reviewer 请求")
    admission = _read(admission_path)
    if admission.get("paper_admission") != "pass" or admission.get("paper_type") != "submission_candidate":
        raise ValueError("Paper Admission 未通过，不能创建 R5 Reviewer 请求")
    stages = {name: _stage_status(run_dir / "reports" / name, allowed) for name, allowed in STAGE_FILES.items()}
    blocking = {name: state for name, state in stages.items() if state in {"DRAFT", "PENDING", "REVISE", "BLOCKED"}}
    if blocking:
        raise ValueError(f"R1-R4 尚未全部通过：{blocking}")
    return stages


def check_stage_gate(run_dir: Path, stage: str) -> dict[str, Any]:
    """检查阶段是否具备开始条件，防止 R1--R4 退化为末期一次性审核。"""

    run_dir = run_dir.resolve()
    stage = stage.upper()
    if stage not in STAGE_ORDER:
        raise ValueError(f"未知阶段：{stage}，应为 R1、R2、R3 或 R4")
    index = STAGE_ORDER.index(stage)
    blockers: list[str] = []
    report_name, expected = STAGE_REPORTS[stage]
    if stage == "R1":
        question_root = run_dir / "questions"
        if not question_root.is_dir() or not any(question_root.glob("*/question.json")):
            blockers.append("缺少题面拆解 question.json，不能开始 R1")
    else:
        previous = STAGE_ORDER[index - 1]
        previous_gate = check_stage_gate(run_dir, previous)
        if previous_gate["status"] != "READY":
            blockers.extend(f"{previous}: {item}" for item in previous_gate["blockers"])

    question_configs = []
    for question_path in sorted((run_dir / "questions").glob("*/question.json")):
        try:
            question_configs.append(_read(question_path))
        except ValueError as exc:
            blockers.append(str(exc))

    if stage == "R2":
        missing_results = [
            str(question.get("id", "<unknown>")).lower()
            for question in question_configs
            if question.get("required", True)
            and not (run_dir / "questions" / str(question.get("id", "")).lower() / "results" / "result.json").is_file()
        ]
        if missing_results:
            blockers.append(f"缺少问级 result.json，不能开始 R2：{missing_results}")
    elif stage == "R3":
        if not (run_dir / "paper" / "main.typ").is_file():
            blockers.append("缺少 paper/main.typ 初稿，不能开始 R3 论文逻辑审核")
        missing_papers = [
            str(question.get("id", "")).lower()
            for question in question_configs
            if question.get("required", True)
            and not (run_dir / "questions" / str(question.get("id", "")).lower() / "paper.typ").is_file()
        ]
        if missing_papers:
            blockers.append(f"缺少问级论文初稿，不能开始 R3：{missing_papers}")
    elif stage == "R4":
        required = (
            run_dir / "verify_report.json",
            run_dir / "result_ledger.json",
            run_dir / "paper" / "submission.pdf",
            run_dir / "package" / "submission.pdf",
            run_dir / "package" / "support.zip",
        )
        for path in required:
            if not path.is_file():
                blockers.append(f"缺少 R4 所需派生产物：{path.relative_to(run_dir).as_posix()}")
        verify_report = run_dir / "verify_report.json"
        if verify_report.is_file() and _read(verify_report).get("status") != "passed":
            blockers.append("ENGINEERING_VERIFICATION 未通过，不能开始 R4")

    return {
        "stage": stage,
        "status": "READY" if not blockers else "BLOCKED",
        "expected_report_status": expected,
        "blockers": blockers,
    }


def _request_path(run_dir: Path) -> Path:
    return run_dir / REQUEST_PATH


def load_request(run_dir: Path) -> dict[str, Any]:
    return _read(_request_path(run_dir))


def _save_request(run_dir: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(request)
    value["updated_at"] = _now()
    if value.get("status") not in R5_STATUSES:
        raise ValueError(f"R5 状态无效：{value.get('status')}")
    _write(_request_path(run_dir), value)
    archive = run_dir / "review" / "r5" / "requests" / f"{value['request_id']}.json"
    _write(archive, value)
    return value


def prepare_request(run_dir: Path, *, round_number: int = 1, parent_request_id: str | None = None, handoff_dir: str = "review_handoff_round2") -> dict[str, Any]:
    """在前置条件通过后创建一个未派发的 R5 请求。"""

    run_dir = run_dir.resolve()
    stages = _assert_ready(run_dir)
    request = {
        "artifact_type": "contest_v2_r5_review_request",
        "schema_version": "1.0.0",
        "request_id": f"R5-{uuid.uuid4().hex[:16]}",
        "round": round_number,
        "parent_request_id": parent_request_id,
        "reviewer_layer": "R5",
        "scope": "blind_full_review",
        "status": "REQUEST_READY",
        "task_id": None,
        "result_path": None,
        "handoff_dir": handoff_dir,
        "trigger": "engineering_pass_paper_admission_pass_r1_r4_clear",
        "stage_snapshot": stages,
        "failure": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    return _save_request(run_dir, request)


def dispatch(run_dir: Path, adapter: ReviewerAdapter | None = None) -> dict[str, Any]:
    """派发当前请求；无 adapter 时明确保留 REQUEST_READY。"""

    run_dir = run_dir.resolve()
    request = load_request(run_dir)
    if request.get("status") in {"CREATED", "RESULT_PENDING", "REVIEW_RECEIVED", "REVIEW_RECOMMENDED", "REVIEW_NEEDS_REPAIR"}:
        return request
    if adapter is None:
        request["failure"] = {"code": "adapter_not_configured", "message": "未配置 Reviewer adapter；等待 AI 编排层派发"}
        return _save_request(run_dir, request)
    request["status"] = "CREATION_PENDING"
    request["attempts"] = int(request.get("attempts", 0)) + 1
    _save_request(run_dir, request)
    try:
        response = dict(adapter.create(request))
        task_id = response.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Reviewer adapter 返回值缺少 task_id")
        request.update({"status": "CREATED", "task_id": task_id, "provider": response.get("provider", "external"), "failure": None})
    except Exception as exc:
        request.update({"status": "CREATION_FAILED", "failure": {"code": "adapter_create_failed", "message": str(exc)}})
    return _save_request(run_dir, request)


def collect(run_dir: Path, adapter: ReviewerAdapter) -> dict[str, Any]:
    """回收 R5 结果，失败时落盘并保留可重试状态。"""

    run_dir = run_dir.resolve()
    request = load_request(run_dir)
    task_id = request.get("task_id")
    if request.get("status") != "CREATED" or not isinstance(task_id, str) or not task_id:
        raise ValueError("当前 R5 请求没有可回收的 task_id")
    request["status"] = "RESULT_PENDING"
    _save_request(run_dir, request)
    try:
        result = dict(adapter.result(task_id))
        decision = result.get("conclusion") or result.get("decision")
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"Reviewer 结论无效：{decision}")
        result_path = run_dir / "review" / "r5" / f"{request['request_id']}.json"
        _write(result_path, result)
        request.update({"status": "REVIEW_RECOMMENDED" if decision == "SUBMISSION_RECOMMENDED" else "REVIEW_NEEDS_REPAIR", "result_path": result_path.relative_to(run_dir).as_posix(), "failure": None, "decision": decision})
    except Exception as exc:
        request.update({"status": "RESULT_FAILED", "failure": {"code": "adapter_result_failed", "message": str(exc)}})
    return _save_request(run_dir, request)


def prepare_rereview(run_dir: Path, *, handoff_dir: str = "review_handoff_round2") -> dict[str, Any]:
    """在上一轮要求修订且产物重新通过前置审核后创建新的复审请求。"""

    previous = load_request(run_dir)
    if previous.get("status") != "REVIEW_NEEDS_REPAIR":
        raise ValueError("当前请求没有待修补的 Reviewer 结论")
    return prepare_request(run_dir, round_number=int(previous.get("round", 1)) + 1, parent_request_id=str(previous["request_id"]), handoff_dir=handoff_dir)
