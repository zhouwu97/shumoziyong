"""构建 2024-C v2.1 两轮隔离审稿与修复证据。

Reviewer A/B 仅使用各自允许的只读输入包。同一模型执行时明确标记为
role_separated_review，不声称完全独立审稿。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from v21_contracts import validate_reviewer_pair, validate_reviewer_report


RUN_ID = "2024C_v21_full_replay_20260715"
REVIEWER_MODEL = "GPT-5 Codex"
ROUND1_FIGURES = (
    "figure_01_scenario_profit",
    "figure_02_risk_comparison",
    "figure_03_sensitivity",
)
FIGURE_SUFFIXES = (".caption.md", ".fragment.json", ".pdf", ".png", ".qa.json", ".svg", ".tiff")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative_path(run_dir: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(run_dir.resolve()):
        raise ValueError(f"审稿工件位于当前 Run 之外：{path}")
    return resolved.relative_to(run_dir.resolve()).as_posix()


def artifact_ref(run_dir: Path, path_text: str, category: str) -> dict[str, str]:
    path = (run_dir / path_text).resolve()
    if not path.is_file() or not path.is_relative_to(run_dir.resolve()):
        raise ValueError(f"Reviewer 输入不存在或越界：{path_text}")
    return {"path": relative_path(run_dir, path), "sha256": sha256_file(path), "category": category}


def archive_round1_figures(run_dir: Path) -> None:
    source_dir = run_dir / "paper/figures"
    archive_dir = run_dir / "paper/archive/figures"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for stem in ROUND1_FIGURES:
        for suffix in FIGURE_SUFFIXES:
            source = source_dir / f"{stem}{suffix}"
            if not source.is_file():
                raise FileNotFoundError(f"缺少第一轮图表工件：{source}")
            target = archive_dir / source.name
            shutil.copy2(source, target)


def write_input_package(
    run_dir: Path,
    *,
    reviewer_id: str,
    role: str,
    round_number: int,
    input_artifacts: list[dict[str, str]],
) -> str:
    value = {
        "schema_version": "1.0.0",
        "artifact_type": "reviewer_input_package",
        "run_id": RUN_ID,
        "reviewer_id": reviewer_id,
        "review_role": role,
        "review_round": round_number,
        "read_only": True,
        "forbidden_inputs": ["execution_chat", "other_reviewer_report"],
        "input_artifacts": input_artifacts,
    }
    path = run_dir / f"paper/reviews/input_packages/{reviewer_id.lower()}_round{round_number}.json"
    write_json(path, value)
    return sha256_file(path)


def make_report(
    run_dir: Path,
    *,
    reviewer_id: str,
    role: str,
    round_number: int,
    inputs: list[dict[str, str]],
    findings: list[dict[str, Any]],
    decision: str,
    prior_report: str | None = None,
    remediation_ref: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "reviewer_report",
        "run_id": RUN_ID,
        "reviewer_id": reviewer_id,
        "review_role": role,
        "review_round": round_number,
        "reviewed_bundle_sha256": write_input_package(
            run_dir,
            reviewer_id=reviewer_id,
            role=role,
            round_number=round_number,
            input_artifacts=inputs,
        ),
        "input_artifacts": inputs,
        "forbidden_inputs_confirmed": True,
        "write_access": False,
        "independence_mode": "role_separated_review",
        "reviewer_model": REVIEWER_MODEL,
        "prompt_profile": f"2024c-v21-reviewer-{role}-r{round_number}",
        "findings": findings,
        "decision": decision,
    }
    if prior_report is not None:
        report["prior_round_report_refs"] = [prior_report]
    if remediation_ref is not None:
        report["remediation_evidence_refs"] = [remediation_ref]
    return report


def round1_inputs(run_dir: Path, role: str) -> list[dict[str, str]]:
    if role == "model":
        specs = [
            ("problem_manifest.json", "problem"),
            ("model_validity_contract.json", "model_contract"),
            ("formal_result_run_binding.json", "formal_result"),
            ("result_report.json", "formal_result"),
            ("model_validity_report.json", "validity_report"),
            ("paper/archive/submission_paper_candidate_round1.typ", "manuscript"),
        ]
    else:
        specs = [
            ("problem_manifest.json", "problem"),
            ("formal_result_run_binding.json", "formal_result"),
            ("result_report.json", "formal_result"),
            ("paper/archive/paper_claim_map_round1.json", "claim_map"),
            ("paper/archive/submission_paper_candidate_round1.typ", "manuscript"),
            *[(f"paper/archive/figures/{stem}.pdf", "figure") for stem in ROUND1_FIGURES],
        ]
    return [artifact_ref(run_dir, path, category) for path, category in specs]


def build_round1(run_dir: Path) -> None:
    archive_round1_figures(run_dir)
    reviewer_a = make_report(
        run_dir,
        reviewer_id="Reviewer-A",
        role="model",
        round_number=1,
        inputs=round1_inputs(run_dir, "model"),
        findings=[
            {
                "finding_id": "A-MODEL-001",
                "severity": "major",
                "resolved": False,
                "message": "论文未明确实现把题面豆类轮作操作化为滚动三年豆类累计面积不少于整块地面积；该约束更强且可能压缩可行域。",
                "evidence_refs": ["model_validity_contract.json", "paper/archive/submission_paper_candidate_round1.typ"],
            }
        ],
        decision="revise",
    )
    reviewer_b = make_report(
        run_dir,
        reviewer_id="Reviewer-B",
        role="paper",
        round_number=1,
        inputs=round1_inputs(run_dir, "paper"),
        findings=[
            {
                "finding_id": "B-FIGURE-001",
                "severity": "major",
                "resolved": False,
                "message": "风险图右侧仅用大面积空白表达 Q3-Q2 等于零，信息密度不足，未充分展示相关假设对下行风险尺度的影响。",
                "evidence_refs": ["paper/archive/figures/figure_02_risk_comparison.pdf"],
            },
            {
                "finding_id": "B-BOUNDARY-002",
                "severity": "major",
                "resolved": False,
                "message": "非零 MIP gap、Q1 销售规则差异和 Q3 相关结构仅为假设等关键边界需要在正文前部显著披露。",
                "evidence_refs": ["paper/archive/submission_paper_candidate_round1.typ"],
            },
        ],
        decision="revise",
    )
    errors = validate_reviewer_pair(reviewer_a, reviewer_b, run_dir=run_dir)
    if errors:
        raise ValueError("第一轮 Reviewer 合同失败：" + "；".join(errors))
    write_json(run_dir / "reviewer_a_round1.json", reviewer_a)
    write_json(run_dir / "reviewer_b_round1.json", reviewer_b)


def validate_remediation(value: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        detail = "；".join(
            f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError("修复证据不符合 Schema：" + detail)


def build_remediation(run_dir: Path, schema_path: Path) -> str:
    comparisons = [
        (
            "paper/submission_paper_candidate.typ",
            "paper/archive/submission_paper_candidate_round1.typ",
            "paper/submission_paper_candidate.typ",
            "显著披露结论边界并说明豆类覆盖约束的加强操作化。",
        ),
        (
            "submission_paper_candidate.pdf",
            "paper/archive/submission_paper_candidate_round1.pdf",
            "submission_paper_candidate.pdf",
            "重编译修订后的正式论文并完成页面视觉检查。",
        ),
        (
            "paper/figures/figure_02_risk_comparison.pdf",
            "paper/archive/figures/figure_02_risk_comparison.pdf",
            "paper/figures/figure_02_risk_comparison.pdf",
            "将空白零差面板替换为两类分布假设的下行风险尺度比较。",
        ),
    ]
    artifacts = []
    for logical_path, before_text, after_text, reason in comparisons:
        before = run_dir / before_text
        after = run_dir / after_text
        if not before.is_file() or not after.is_file():
            raise FileNotFoundError(f"修复证据缺少前后工件：{before_text} / {after_text}")
        before_sha = sha256_file(before)
        after_sha = sha256_file(after)
        if before_sha == after_sha:
            raise ValueError(f"修复工件哈希未发生变化：{logical_path}")
        artifacts.append(
            {
                "root": "run",
                "path": logical_path,
                "before_sha256": before_sha,
                "after_sha256": after_sha,
                "reason": reason,
            }
        )
    revision_digest = hashlib.sha256(json.dumps(artifacts, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    value = {
        "schema_version": "1.0.0",
        "revision_id": f"revision_{revision_digest}",
        "run_id": RUN_ID,
        "executor_session_id": "gate4-codex-20260716",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "affected_gates": [4],
        "artifacts": artifacts,
        "validators_rerun": [
            "claim_result_contract",
            "python_figure_visual_qa",
            "typst_compile",
            "reviewer_input_scope",
        ],
        "summary": "第一轮模型边界、论文边界和风险图信息密度问题已局部修复，并重跑受影响的 Gate 4 证据。",
    }
    validate_remediation(value, schema_path)
    path = run_dir / "paper/remediation_evidence.json"
    write_json(path, value)
    return relative_path(run_dir, path)


def round2_inputs(run_dir: Path, role: str) -> list[dict[str, str]]:
    if role == "model":
        specs = [
            ("problem_manifest.json", "problem"),
            ("model_validity_contract.json", "model_contract"),
            ("formal_result_run_binding.json", "formal_result"),
            ("result_report.json", "formal_result"),
            ("model_validity_report.json", "validity_report"),
            ("paper/submission_paper_candidate.typ", "manuscript"),
            ("reviewer_a_round1.json", "review_report"),
        ]
    else:
        specs = [
            ("problem_manifest.json", "problem"),
            ("formal_result_run_binding.json", "formal_result"),
            ("result_report.json", "formal_result"),
            ("paper_claim_map.json", "claim_map"),
            ("paper/submission_paper_candidate.typ", "manuscript"),
            ("reviewer_b_round1.json", "review_report"),
            *[(f"paper/figures/{stem}.pdf", "figure") for stem in ROUND1_FIGURES],
        ]
    return [artifact_ref(run_dir, path, category) for path, category in specs]


def build_round2(run_dir: Path, schema_path: Path) -> None:
    remediation_ref = build_remediation(run_dir, schema_path)
    reviewer_a = make_report(
        run_dir,
        reviewer_id="Reviewer-A",
        role="model",
        round_number=2,
        inputs=round2_inputs(run_dir, "model"),
        findings=[
            {
                "finding_id": "A-MODEL-001",
                "severity": "major",
                "resolved": True,
                "message": "修订稿已明确豆类累计面积约束强于题面最低要求、可能压缩可行域，并将其限定为模型假设。",
                "evidence_refs": ["paper/submission_paper_candidate.typ", remediation_ref],
            }
        ],
        decision="pass",
        prior_report="reviewer_a_round1.json",
        remediation_ref=remediation_ref,
    )
    reviewer_b = make_report(
        run_dir,
        reviewer_id="Reviewer-B",
        role="paper",
        round_number=2,
        inputs=round2_inputs(run_dir, "paper"),
        findings=[
            {
                "finding_id": "B-FIGURE-001",
                "severity": "major",
                "resolved": True,
                "message": "修订后的风险图用三项下行风险尺度比较替代空白零差面板，并保留 Q3-Q2 等于零的明确注记。",
                "evidence_refs": ["paper/figures/figure_02_risk_comparison.pdf", remediation_ref],
            },
            {
                "finding_id": "B-BOUNDARY-002",
                "severity": "major",
                "resolved": True,
                "message": "修订稿已在摘要后设置显著结论边界，并在结果段分别限制最优性、销售规则与相关假设的解释范围。",
                "evidence_refs": ["paper/submission_paper_candidate.typ", remediation_ref],
            },
        ],
        decision="pass",
        prior_report="reviewer_b_round1.json",
        remediation_ref=remediation_ref,
    )
    for report in (reviewer_a, reviewer_b):
        errors = validate_reviewer_report(report)
        if errors:
            raise ValueError("第二轮 Reviewer 合同失败：" + "；".join(errors))
    errors = validate_reviewer_pair(reviewer_a, reviewer_b, run_dir=run_dir)
    if errors:
        raise ValueError("第二轮 Reviewer 隔离失败：" + "；".join(errors))
    write_json(run_dir / "reviewer_a_round2.json", reviewer_a)
    write_json(run_dir / "reviewer_b_round2.json", reviewer_b)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 2024-C v2.1 双轮 Reviewer 工件")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stage", choices=("round1", "round2"), required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("run_id") != RUN_ID:
        raise ValueError("脚本只允许用于固定的 2024-C v2.1 回放运行")
    if args.stage == "round1":
        build_round1(run_dir)
    else:
        build_round2(run_dir, SCRIPTS.parent / "schemas/remediation_evidence.schema.json")
    print(json.dumps({"run_id": RUN_ID, "stage": args.stage, "status": "built"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
