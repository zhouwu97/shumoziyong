"""派生 Gate F1/F2/F3 状态，阻止实质内容缺口进入人工终审。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_ID_PATTERN = re.compile(r"^PC-[a-f0-9]{24}$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"必须是 JSON 对象：{path}")
    return value


def derive_gate_f_outcome(
    *, f1_status: str, f2_status: str, f3_status: str
) -> tuple[str, bool]:
    """从三个阶段状态唯一派生 Gate F 总状态和 Gate G 资格。"""
    if f1_status not in {"passed", "failed", "pending"}:
        raise ValueError(f"非法 F1 状态：{f1_status!r}")
    if f2_status not in {"passed", "content_repair_required", "pending"}:
        raise ValueError(f"非法 F2 状态：{f2_status!r}")
    if f3_status not in {"passed", "failed", "pending"}:
        raise ValueError(f"非法 F3 状态：{f3_status!r}")
    if f1_status != "passed":
        return "mechanically_invalid", False
    if f2_status != "passed":
        return "content_repair_required", False
    if f3_status == "pending":
        return "ready_for_independent_paper_review", False
    if f3_status == "failed":
        return "independent_paper_review_failed", False
    return "independent_paper_review_passed", True


def validate_f3_review_references(run_dir: Path, review: Mapping[str, Any]) -> None:
    """现场验证 F3 审核绑定的 Candidate、F2 报告和不可变审批历史。"""
    root = run_dir.resolve()
    report_path = root / "paper_substantive_completeness_report.json"
    if not report_path.is_file():
        raise ValueError("F3 引用的完整性报告不存在")
    if review.get("completeness_report_sha256") != sha256_file(report_path):
        raise ValueError("F3 completeness_report_sha256 与现场报告不一致")
    candidate_path: Path
    pointer_payload: dict[str, Any] | None = None
    pointer = root / "current_paper_candidate.json"
    if pointer.is_file():
        pointer_payload = _load(pointer)
        pointer_id = pointer_payload.get("candidate_id")
        if not isinstance(pointer_id, str) or not CANDIDATE_ID_PATTERN.fullmatch(pointer_id):
            raise ValueError("current_paper_candidate.json 缺少合法 candidate_id")
        candidate_path = root / "paper_candidates" / pointer_id / "paper_candidate_manifest.json"
        if candidate_path.parent.name != pointer_id:
            raise ValueError("Candidate 路径中的 ID 与 pointer 不一致")
    else:
        candidate_path = root / "paper_candidate_manifest.json"
    if not candidate_path.is_file():
        raise ValueError("F3 引用的 Candidate 文件不存在")
    candidate = _load(candidate_path)
    manifest_id = candidate.get("candidate_id")
    if not isinstance(manifest_id, str) or not CANDIDATE_ID_PATTERN.fullmatch(manifest_id):
        raise ValueError("Candidate Manifest 缺少合法 candidate_id")
    if pointer_payload is not None and pointer_payload.get("candidate_id") != manifest_id:
        raise ValueError("Candidate pointer ID 与 Manifest ID 不一致")
    if review.get("reviewed_candidate_id") != manifest_id:
        raise ValueError("F3 reviewed_candidate_id 与当前 Candidate 不一致")
    if review.get("candidate_sha256") != sha256_file(candidate_path):
        raise ValueError("F3 candidate_sha256 与现场 Candidate 不一致")
    approval = str(review.get("approval_record", ""))
    approval_path = (root / approval).resolve()
    if not approval or not approval_path.is_file() or not approval_path.is_relative_to(root):
        raise ValueError("F3 approval_record 不存在或越出当前 Run")
    history_path = root / "paper_reader_review_history.jsonl"
    if not history_path.is_file():
        raise ValueError("F3 审核尚未进入 paper_reader_review_history.jsonl")
    approval_relative = approval_path.relative_to(root).as_posix()
    approval_sha = sha256_file(approval_path)
    recorded = False
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("path") == approval_relative and event.get("sha256") == approval_sha:
            recorded = True
            break
    if not recorded:
        raise ValueError("F3 approval_record 未进入不可变审核历史")


def build_gate_f_status(
    *,
    f1_passed: bool,
    completeness_report: Mapping[str, Any],
    f3_status: str = "pending",
    f3_review: Mapping[str, Any] | None = None,
    completeness_report_path: Path | None = None,
) -> dict[str, Any]:
    """按固定优先级派生 Gate F 状态。"""
    f1_status = "passed" if f1_passed else "failed"
    f2_status = "passed" if completeness_report.get("status") == "passed" else "content_repair_required"
    status, eligible_for_gate_g = derive_gate_f_outcome(
        f1_status=f1_status,
        f2_status=f2_status,
        f3_status=f3_status,
    )
    issues: list[str] = []
    if f1_status != "passed":
        issues.append("F1 机械正确性未通过")
    if f1_status == "passed" and f2_status != "passed":
        issues.append("F2 实质内容完整性未通过")
    if f2_status == "passed" and f3_status == "failed":
        issues.append("F3 独立论文审核未通过")
    if f3_status == "pending" and f3_review is not None:
        raise ValueError("F3 pending 不得携带终审记录")
    if f3_status in {"passed", "failed"}:
        if f1_status != "passed" or f2_status != "passed":
            raise ValueError("只有 F1/F2 通过后才允许记录 F3 终态")
        if not f3_review or f3_review.get("reviewer_type") != "human":
            raise ValueError("F3 终态必须绑定 reviewer_type=human 的独立论文审核")
        expected_decision = "approved" if f3_status == "passed" else "rejected"
        if f3_review.get("decision") != expected_decision:
            raise ValueError(f"F3 {f3_status} 必须绑定 decision={expected_decision}")
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_gate_f_status",
        "f1_status": f1_status,
        "f2_status": f2_status,
        "f3_status": f3_status,
        "status": status,
        "eligible_for_gate_g": eligible_for_gate_g,
        "issues": issues,
    }
    if f3_review is not None:
        result["f3_review"] = dict(f3_review)
    if completeness_report_path is not None:
        result["completeness_report_sha256"] = sha256_file(completeness_report_path)
    schema = _load(ROOT / "schemas" / "paper_gate_f_status.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise ValueError("Gate F 状态 Schema 校验失败：" + "; ".join(error.message for error in errors[:8]))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="派生 Gate F1/F2/F3 状态")
    parser.add_argument("--f1-status", choices=("passed", "failed"), required=True)
    parser.add_argument("--completeness-report", type=Path, required=True)
    parser.add_argument("--f3-status", choices=("passed", "failed", "pending"), default="pending")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = _load(args.completeness_report)
    status = build_gate_f_status(
        f1_passed=args.f1_status == "passed",
        completeness_report=report,
        f3_status=args.f3_status,
        completeness_report_path=args.completeness_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status["status"], "eligible_for_gate_g": status["eligible_for_gate_g"]}, ensure_ascii=False))
    return 0 if status["eligible_for_gate_g"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
