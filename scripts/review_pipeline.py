"""候选稿版本化、独立 Reviewer 产物与可验证输入工作区。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from atomic_io import atomic_write_bytes
from review_ledger import (
    CANONICALIZATION_VERSION,
    HISTORY_EVENT_VERSION,
    acquire_run_write_lock,
    append_immutable_review,
    canonical_json_bytes,
    sha256_bytes,
    verify_history,
)


ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 必须为对象：{path}")
    return value


def _schema(value: dict[str, Any], name: str) -> None:
    from jsonschema import Draft202012Validator, FormatChecker

    schema = _json(ROOT / "schemas" / name)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ValueError("；".join(error.message for error in errors))


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"引用文件不存在或越出 Run：{relative}")
    return path


def _candidate_history(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "paper_candidate_history.jsonl"
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    previous: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if not isinstance(item, dict) or item.get("previous_event_sha256") != previous:
            raise ValueError("paper_candidate_history 哈希链前序无效")
        if item.get("history_event_version") != HISTORY_EVENT_VERSION or item.get("canonicalization_version") != CANONICALIZATION_VERSION:
            raise ValueError("paper_candidate_history 合同版本不支持")
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or not re.fullmatch(r"PC-[0-9]{4}", candidate_id):
            raise ValueError("paper_candidate_history candidate_id 非法")
        claimed = item.get("event_sha256")
        payload = dict(item); payload.pop("event_sha256", None)
        if claimed != sha256_bytes(canonical_json_bytes(payload)):
            raise ValueError("paper_candidate_history 哈希链无效")
        manifest_path = run_dir / "paper_candidates" / candidate_id / "paper_candidate_manifest.json"
        if not manifest_path.is_file() or item.get("candidate_manifest_sha256") != sha256_bytes(manifest_path.read_bytes()):
            raise ValueError("paper_candidate_history 引用的 Candidate Manifest 不存在或哈希不一致")
        previous = str(claimed); items.append(item)
    return items


def _candidate_event(record: Mapping[str, Any], manifest_sha: str, previous: str | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "history_event_version": HISTORY_EVENT_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "candidate_id": record["candidate_id"],
        "parent_candidate_id": record["parent_candidate_id"],
        "candidate_manifest_sha256": manifest_sha,
        "created_at": record["created_at"],
        "trigger_review_id": record.get("trigger_review_id"),
        "reason": record["reason"],
        "previous_event_sha256": previous,
    }
    event["event_sha256"] = sha256_bytes(canonical_json_bytes(event))
    return event


def _reconcile_orphan_candidates(run_dir: Path) -> list[dict[str, Any]]:
    """恢复已落盘但尚未写入 history 的 Candidate，拒绝任何顺序歧义。"""
    history = _candidate_history(run_dir)
    candidate_root = run_dir / "paper_candidates"
    if not candidate_root.is_dir():
        return history
    recorded = {str(item["candidate_id"]) for item in history}
    orphan_directories = [path for path in sorted(candidate_root.glob("PC-*")) if path.name not in recorded]
    for candidate_dir in orphan_directories:
        if not candidate_dir.is_dir() or not re.fullmatch(r"PC-[0-9]{4}", candidate_dir.name):
            raise ValueError("存在非法 Candidate 目录")
        expected_id = f"PC-{len(history) + 1:04d}"
        if candidate_dir.name != expected_id:
            raise ValueError("孤立 Candidate 的编号必须紧接 history 末端")
        manifest_path = candidate_dir / "paper_candidate_manifest.json"
        record = _json(manifest_path)
        _schema(record, "review_candidate_manifest.schema.json")
        expected_parent = history[-1]["candidate_id"] if history else None
        if record.get("candidate_id") != expected_id or record.get("parent_candidate_id") != expected_parent:
            raise ValueError("孤立 Candidate 的身份或父级不连续")
        if record.get("run_id") != _json(run_dir / "run_manifest.json").get("run_id"):
            raise ValueError("孤立 Candidate 绑定了其他 Run")
        manifest_sha = sha256_bytes(manifest_path.read_bytes())
        history.append(_candidate_event(record, manifest_sha, history[-1]["event_sha256"] if history else None))
    if orphan_directories:
        payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in history)
        atomic_write_bytes(run_dir / "paper_candidate_history.jsonl", payload.encode("utf-8"))
    return history


def register_paper_candidate(
    run_dir: Path,
    source_paths: list[str],
    *,
    reason: str,
    parent_candidate_id: str | None = None,
    trigger_review_id: str | None = None,
) -> dict[str, Any]:
    """复制明确来源为不可变 Candidate，并以追加式哈希历史更新当前指针。"""
    run_dir = run_dir.resolve()
    manifest = _json(run_dir / "run_manifest.json")
    with acquire_run_write_lock(run_dir):
        history = _reconcile_orphan_candidates(run_dir)
        expected_parent = history[-1]["candidate_id"] if history else None
        if parent_candidate_id != expected_parent:
            raise ValueError("parent_candidate_id 必须精确引用当前候选稿；首稿必须为 null")
        versioned_run = _run_contract_enabled(run_dir, "gate_5_review_contract_version")
        if expected_parent is None and trigger_review_id is not None:
            raise ValueError("首个 Candidate 不得伪造 Gate 5 触发审核")
        if expected_parent is not None and versioned_run and not trigger_review_id:
            raise ValueError("修订 Candidate 必须绑定触发它的 Gate 5 Review")
        if trigger_review_id is not None:
            entries, _head = verify_history(run_dir, "gate_5_review_history.jsonl")
            entry = next((item for item in entries if item.get("review_id") == trigger_review_id), None)
            if entry is None:
                raise ValueError("trigger_review_id 未进入 Gate 5 不可变 history")
            trigger = _json(_inside(run_dir, str(entry["path"])))
            if trigger.get("decision") != "needs_revision" or trigger.get("candidate_id") != expected_parent:
                raise ValueError("修订 Candidate 必须由指向当前父 Candidate 的 needs_revision 触发")
        candidate_id = f"PC-{len(history) + 1:04d}"
        candidate_dir = run_dir / "paper_candidates" / candidate_id
        if candidate_dir.exists():
            raise FileExistsError(f"Candidate 不可覆盖：{candidate_dir}")
        sources: list[tuple[str, Path]] = []
        target_names: set[str] = set()
        for source_text in source_paths:
            source = _inside(run_dir, source_text)
            if source.name in target_names:
                raise ValueError("Candidate source_paths 不得包含同名文件")
            target_names.add(source.name)
            sources.append((source_text, source))
        candidate_dir.mkdir(parents=True)
        files: list[dict[str, str]] = []
        for source_text, source in sources:
            target = candidate_dir / source.name
            atomic_write_bytes(target, source.read_bytes())
            files.append({"source_path": source_text, "path": target.relative_to(candidate_dir).as_posix(), "sha256": sha256_bytes(target.read_bytes())})
        record: dict[str, Any] = {
            "schema_version": "1.0.0",
            "artifact_type": "review_candidate_manifest",
            "candidate_id": candidate_id,
            "run_id": manifest["run_id"],
            "parent_candidate_id": parent_candidate_id,
            "created_at": _now(),
            "reason": reason,
            "trigger_review_id": trigger_review_id,
            "source_files": files,
        }
        if not history:
            legacy = run_dir / "gate_artifacts" / "gate_4.manifest.json"
            if legacy.is_file():
                record["legacy_gate_4_manifest_sha256"] = sha256_bytes(legacy.read_bytes())
        _schema(record, "review_candidate_manifest.schema.json")
        manifest_path = candidate_dir / "paper_candidate_manifest.json"
        atomic_write_bytes(manifest_path, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        manifest_sha = sha256_bytes(manifest_path.read_bytes())
        event = _candidate_event(record, manifest_sha, history[-1]["event_sha256"] if history else None)
        history.append(event)
        atomic_write_bytes(run_dir / "paper_candidate_history.jsonl", "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in history).encode("utf-8"))
        pointer = {"candidate_id": candidate_id, "candidate_manifest_sha256": manifest_sha}
        atomic_write_bytes(run_dir / "current_paper_candidate.json", (json.dumps(pointer, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return {**pointer, "path": manifest_path.relative_to(run_dir).as_posix()}


def current_candidate(run_dir: Path) -> dict[str, str]:
    """从 Candidate history 重建并校验当前指针。"""
    history = _candidate_history(run_dir)
    if not history:
        raise ValueError("尚未注册论文 Candidate")
    item = history[-1]
    path = run_dir / "paper_candidates" / str(item["candidate_id"]) / "paper_candidate_manifest.json"
    if not path.is_file() or sha256_bytes(path.read_bytes()) != item["candidate_manifest_sha256"]:
        raise ValueError("当前 Candidate Manifest 不存在或哈希不一致")
    expected = {"candidate_id": str(item["candidate_id"]), "candidate_manifest_sha256": str(item["candidate_manifest_sha256"])}
    if _json(run_dir / "current_paper_candidate.json") != expected:
        raise ValueError("current_paper_candidate 不能由有效 history 重建")
    return expected


def _run_contract_enabled(run_dir: Path, field: str) -> bool:
    return bool(_json(run_dir / "run_manifest.json").get(field))


def _latest_reasonableness_review(run_dir: Path) -> dict[str, Any]:
    entries, _head = verify_history(run_dir, "reasonableness_review_history.jsonl")
    if not entries:
        raise ValueError("缺少 Reasonableness Review")
    entry = entries[-1]
    path = _inside(run_dir, str(entry["path"]))
    review = _json(path)
    _schema(review, "reasonableness_review.schema.json")
    return {
        "review": review,
        "path": str(entry["path"]),
        "sha256": str(entry["sha256"]),
        "history_head_sha256": _head,
    }


def _validate_reference(run_dir: Path, value: object, *, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须包含 path 和 sha256")
    path_text = value.get("path")
    digest = value.get("sha256")
    if not isinstance(path_text, str) or not isinstance(digest, str):
        raise ValueError(f"{label} 必须包含 path 和 sha256")
    path = _inside(run_dir, path_text)
    if sha256_bytes(path.read_bytes()) != digest:
        raise ValueError(f"{label} 哈希与现场文件不一致")


def review_pipeline_evidence_artifacts(run_dir: Path) -> list[tuple[str, str, str]]:
    """列出已存在的 Reviewer 与 Candidate 证据，供封存清单精确绑定。"""
    specs: list[tuple[str, str, str]] = []
    review_specs = (
        ("reasonableness", "reasonableness_review_history.jsonl", "reviews/reasonableness"),
        ("technical", "technical_review_history.jsonl", "reviews/technical"),
        ("paper_reader", "paper_reader_review_history.jsonl", "reviews/paper_reader"),
    )
    for kind, history_name, _directory in review_specs:
        history_path = run_dir / history_name
        if not history_path.is_file():
            continue
        specs.append((history_name, f"{kind}_review_history", "application/jsonlines"))
        entries, _head = verify_history(run_dir, history_name)
        for entry in entries:
            review_id = str(entry["review_id"])
            specs.append((str(entry["path"]), f"{kind}_review_record:{review_id}", "application/json"))
    history_path = run_dir / "paper_candidate_history.jsonl"
    if not history_path.is_file():
        return specs
    specs.append(("paper_candidate_history.jsonl", "paper_candidate_history", "application/jsonlines"))
    candidates = _candidate_history(run_dir)
    if not candidates:
        return specs
    current_candidate(run_dir)
    specs.append(("current_paper_candidate.json", "current_paper_candidate", "application/json"))
    for event in candidates:
        candidate_id = str(event["candidate_id"])
        manifest_path = f"paper_candidates/{candidate_id}/paper_candidate_manifest.json"
        specs.append((manifest_path, f"paper_candidate_manifest:{candidate_id}", "application/json"))
        manifest = _json(run_dir / manifest_path)
        for source in manifest["source_files"]:
            path_text = f"paper_candidates/{candidate_id}/{source['path']}"
            specs.append((path_text, f"paper_candidate_file:{candidate_id}:{source['path']}", "application/octet-stream"))
    return specs


def record_technical_review(run_dir: Path, review: Mapping[str, Any]) -> dict[str, Any]:
    """保存不可变技术审核，审核必须绑定当前 Candidate。"""
    candidate = current_candidate(run_dir)
    payload = dict(review)
    if payload.get("candidate_id") != candidate["candidate_id"] or payload.get("candidate_manifest_sha256") != candidate["candidate_manifest_sha256"]:
        raise ValueError("Technical Review 必须绑定当前 Candidate")
    if payload.get("decision") == "approved" and (payload.get("required_actions") or any(item.get("severity") == "blocking" for item in payload.get("issues", []))):
        raise ValueError("approved Technical Review 不得保留阻断问题或修订动作")
    if _run_contract_enabled(run_dir, "reasonableness_contract_version"):
        latest = _latest_reasonableness_review(run_dir)
        if latest["review"].get("decision") != "approved":
            raise ValueError("Reasonableness Review 未批准，Technical Review 不得确认提交资格")
        reference = payload.get("reasonableness_review_ref")
        _validate_reference(run_dir, reference, label="reasonableness_review_ref")
        if reference != {"path": latest["path"], "sha256": latest["sha256"]}:
            raise ValueError("Technical Review 必须引用当前 approved Reasonableness Review")
        restrictions = list(latest["review"].get("claim_restrictions", [])) + list(latest["review"].get("required_limitations", []))
        if restrictions:
            closure_refs = payload.get("restriction_closure_refs")
            if not isinstance(closure_refs, list) or not closure_refs:
                raise ValueError("带 Reasonableness 限制时，Technical Review 必须提供限制闭合证据")
            for index, reference in enumerate(closure_refs, start=1):
                _validate_reference(run_dir, reference, label=f"restriction_closure_refs[{index}]")
    def validate(value: dict[str, Any]) -> None: _schema(value, "technical_review.schema.json")
    with acquire_run_write_lock(run_dir):
        return append_immutable_review(run_dir, payload, review_directory="reviews/technical", history_filename="technical_review_history.jsonl", validate_review=validate)


def record_paper_reader_review(run_dir: Path, review: Mapping[str, Any]) -> dict[str, Any]:
    """保存独立 Paper Reader 审核；workspace_enforced 才能用于 Required policy。"""
    candidate = current_candidate(run_dir)
    payload = dict(review)
    if payload.get("candidate_id") != candidate["candidate_id"] or payload.get("candidate_manifest_sha256") != candidate["candidate_manifest_sha256"]:
        raise ValueError("Paper Reader Review 必须绑定当前 Candidate")
    isolation = payload.get("isolation", {})
    if isolation.get("isolation_status") == "workspace_enforced" and (isolation.get("repository_mounted") or isolation.get("parent_context_inherited") or isolation.get("network_access")):
        raise ValueError("workspace_enforced 不得挂载仓库、继承上下文或开放网络")
    if isolation.get("isolation_status") == "workspace_enforced":
        _validate_reference(run_dir, isolation.get("execution_attestation"), label="isolation.execution_attestation")
        scores = payload.get("answer_scores")
        if not isinstance(scores, Mapping):
            raise ValueError("workspace_enforced Paper Reader Review 必须记录五项理解评分")
        values = list(scores.values())
        if payload.get("decision") == "approved":
            if scores.get("result_role") == "incorrect" or scores.get("claim_scope") == "incorrect":
                raise ValueError("approved Paper Reader Review 不得反转结果角色或结论边界")
            if sum(value == "correct" for value in values) < 4 or any(value == "incorrect" for value in values):
                raise ValueError("approved Paper Reader Review 未达到 4/5 correct 且其余非 incorrect 的阈值")
            if payload.get("major_misunderstandings"):
                raise ValueError("approved Paper Reader Review 不得保留 major_misunderstandings")
        metadata = payload.get("best_effort_model_metadata")
        required_metadata = {"provider", "model_name", "model_version", "deployment_id", "temperature", "seed"}
        if not isinstance(metadata, Mapping) or set(metadata) != required_metadata:
            raise ValueError("workspace_enforced Paper Reader Review 必须记录完整 best-effort 模型元数据")
    def validate(value: dict[str, Any]) -> None: _schema(value, "paper_reader_review.schema.json")
    with acquire_run_write_lock(run_dir):
        return append_immutable_review(run_dir, payload, review_directory="reviews/paper_reader", history_filename="paper_reader_review_history.jsonl", validate_review=validate)


def approved_supporting_review(run_dir: Path, reference: Mapping[str, Any], *, kind: str, candidate: Mapping[str, str], require_enforced: bool = False) -> None:
    """复验 Gate 5 引用的审核文件、哈希、候选身份与隔离资格。"""
    directories = {"technical": ("reviews/technical", "technical_review.schema.json", "technical_review_history.jsonl"), "paper_reader": ("reviews/paper_reader", "paper_reader_review.schema.json", "paper_reader_review_history.jsonl")}
    directory, schema, history_name = directories[kind]
    path_text = reference.get("path")
    if not isinstance(path_text, str) or not path_text.startswith(directory + "/"):
        raise ValueError(f"{kind} supporting review 路径非法")
    path = _inside(run_dir, path_text)
    if reference.get("sha256") != sha256_bytes(path.read_bytes()):
        raise ValueError(f"{kind} supporting review 哈希不一致")
    if (
        reference.get("candidate_id") != candidate["candidate_id"]
        or reference.get("candidate_manifest_sha256") != candidate["candidate_manifest_sha256"]
    ):
        raise ValueError(f"{kind} supporting review 引用的 Candidate 不一致")
    review = _json(path); _schema(review, schema)
    if review.get("decision") != "approved" or review.get("candidate_id") != candidate["candidate_id"] or review.get("candidate_manifest_sha256") != candidate["candidate_manifest_sha256"]:
        raise ValueError(f"{kind} supporting review 未通过或绑定了旧 Candidate")
    entries, _head = verify_history(run_dir, history_name)
    if not any(item.get("path") == path_text and item.get("sha256") == reference.get("sha256") for item in entries):
        raise ValueError(f"{kind} supporting review 未进入不可变 history")
    if require_enforced and review.get("isolation", {}).get("isolation_status") != "workspace_enforced":
        raise ValueError("Paper Reader supporting review 未达到 workspace_enforced")


def record_reasonableness_review(run_dir: Path, review: Mapping[str, Any]) -> dict[str, Any]:
    """保存 L3 合理性审核；它不改变 Formal Result，只决定能否进入论文阶段。"""
    payload = dict(review)
    if payload.get("run_id") != _json(run_dir / "run_manifest.json").get("run_id"):
        raise ValueError("Reasonableness Review 必须绑定当前 Run")
    if payload.get("decision") == "approved" and payload.get("requested_revision_scope") is not None:
        raise ValueError("approved Reasonableness Review 不得请求修订范围")
    if payload.get("decision") != "approved" and payload.get("requested_revision_scope") is None:
        raise ValueError("失败的 Reasonableness Review 必须明确请求修订范围")
    if payload.get("decision") == "rejected" and payload.get("requested_revision_scope") != "terminal_rejection":
        raise ValueError("rejected Reasonableness Review 必须请求 terminal_rejection")
    if _run_contract_enabled(run_dir, "reasonableness_contract_version"):
        for field in ("reviewed_inputs", "subproblem_reviews", "issues", "required_actions", "restriction_closure_requirements"):
            if field not in payload:
                raise ValueError(f"Reasonableness Review 缺少 {field}")
        for index, reference in enumerate(payload["reviewed_inputs"], start=1):
            _validate_reference(run_dir, reference, label=f"reviewed_inputs[{index}]")
        if payload["decision"] == "approved" and any(
            item.get("severity") == "blocking" for item in payload["issues"]
        ):
            raise ValueError("approved Reasonableness Review 不得保留 blocking issue")
    def validate(value: dict[str, Any]) -> None: _schema(value, "reasonableness_review.schema.json")
    with acquire_run_write_lock(run_dir):
        return append_immutable_review(run_dir, payload, review_directory="reviews/reasonableness", history_filename="reasonableness_review_history.jsonl", validate_review=validate)


def require_approved_reasonableness_review(run_dir: Path) -> dict[str, str]:
    """只接受最近一次不可变审核为 approved，拒绝项保留但阻断 Gate 4。"""
    latest = _latest_reasonableness_review(run_dir)
    if latest["review"].get("decision") != "approved":
        raise ValueError("最近 Reasonableness Review 未批准，不能进入 Gate 4")
    return {"path": latest["path"], "sha256": latest["sha256"], "review_id": str(latest["review"]["review_id"])}


def create_paper_reader_workspace(workspace: Path, *, problem_pdf: Path, submission_pdf: Path, review_contract: Mapping[str, Any], prompt: str) -> dict[str, Any]:
    """创建只含题面、论文和审核合同的输入包；默认不宣称操作系统级隔离。"""
    workspace.mkdir(parents=True, exist_ok=False)
    for source, target in ((problem_pdf, workspace / "problem_statement.pdf"), (submission_pdf, workspace / "submission_paper.pdf")):
        if not source.is_file(): raise FileNotFoundError(source)
        atomic_write_bytes(target, source.read_bytes())
    contract_path = workspace / "review_contract.json"; atomic_write_bytes(contract_path, (json.dumps(review_contract, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    prompt_path = workspace / "review_prompt.txt"; atomic_write_bytes(prompt_path, prompt.encode("utf-8"))
    manifest = {"schema_version": "1.0.0", "allowlist": [path.name for path in (workspace / "problem_statement.pdf", workspace / "submission_paper.pdf", contract_path, prompt_path)], "repository_mounted": False, "parent_context_inherited": False, "network_access": False, "isolation_status": "declared_only"}
    manifest_path = workspace / "workspace_manifest.json"; atomic_write_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {"workspace_manifest_sha256": sha256_bytes(manifest_path.read_bytes()), "problem_sha256": sha256_bytes((workspace / "problem_statement.pdf").read_bytes()), "submission_pdf_sha256": sha256_bytes((workspace / "submission_paper.pdf").read_bytes()), "review_contract_sha256": sha256_bytes(contract_path.read_bytes()), "review_prompt_sha256": sha256_bytes(prompt_path.read_bytes()), "isolation_status": "declared_only"}
