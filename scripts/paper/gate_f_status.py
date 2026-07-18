"""派生 Gate F1/F2/F3 状态，阻止实质内容缺口进入人工终审。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"必须是 JSON 对象：{path}")
    return value


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
    issues: list[str] = []
    if not f1_passed:
        status = "mechanically_invalid"
        issues.append("F1 机械正确性未通过")
    elif f2_status != "passed":
        status = "content_repair_required"
        issues.append("F2 实质内容完整性未通过")
    elif f3_status == "passed":
        if not f3_review or f3_review.get("reviewer_type") != "human":
            raise ValueError("F3 通过必须绑定 reviewer_type=human 的独立论文审核")
        status = "independent_paper_review_passed"
    elif f3_status == "failed":
        if not f3_review or f3_review.get("reviewer_type") != "human":
            raise ValueError("F3 失败也必须保留真人审核记录")
        status = "independent_paper_review_failed"
        issues.append("F3 独立论文审核未通过")
    else:
        status = "ready_for_independent_paper_review"
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_gate_f_status",
        "f1_status": f1_status,
        "f2_status": f2_status,
        "f3_status": f3_status,
        "status": status,
        "eligible_for_gate_g": status == "independent_paper_review_passed",
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
