from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from build_fact_projection import build_projection
from build_qualification_boundary import collect_qualification_boundary
from build_review_freeze import build_review_freeze
from build_rhetoric_bundle import build_bundle
from check_rhetoric_overlap import check_overlap
from paper_compiler_common import (
    ROOT,
    load_json,
    relative_posix,
    sha256_file,
    validate_schema,
    write_json,
)
from parse_typed_exemptions import parse_exemptions
from render_fact_references import render_plan
from retrieve_candidate_cards import retrieve_cards
from run_paper_compiler_fault_injection import run_fault_injections
from validate_exploratory_review import validate_reviews
from validate_fact_projection import validate_projection
from validate_fact_realization import validate_realization


RUN_RELATIVE = Path("runs/2024C_v21_full_replay_20260715")
EVIDENCE_RELATIVE = Path("capability_evidence/paper_compiler_v1_1_1")
CARD_RELATIVE = Path("papers/rhetoric_cards")
SOURCE_TEXT_RELATIVE = Path("tmp/pdfs/A127_clean_extract.txt")
TARGET_BRANCH = "codex/trusted-competition-hardening"
TARGET_COMMIT = "709019768c18b5327a3727ab1e7274c4d89c12fb"
IMPLEMENTATION_BASE_COMMIT = "2c132858c2f271374fcfa80904251a4cc40f5da5"


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def build_baseline_lock(run_dir: Path, baseline_dir: Path) -> dict[str, Any]:
    target_commit = git_value("rev-parse", TARGET_COMMIT)
    implementation_commit = git_value("rev-parse", IMPLEMENTATION_BASE_COMMIT)
    tracked = [
        ROOT / "schemas/paper_claim_map_v2.schema.json",
        ROOT / "scripts/paper/check_claim_bindings.py",
        ROOT / "schemas/formal_result_manifest.schema.json",
        run_dir / "paper_claim_map.json",
        run_dir / "result_report.json",
        run_dir / "paper/submission_paper_candidate.typ",
        baseline_dir / "claim_bindings.json",
        baseline_dir / "argument_graph.json",
        ROOT
        / "高教社杯全国大学生数学建模竞赛优秀论文/2023年高教社杯全国大学生数学建模竞赛优秀论文/A127.pdf",
        ROOT / "tmp/pdfs/A127_clean_extract.txt",
    ]
    lock = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_pilot_baseline_lock",
        "pilot_id": "paper-compiler-2024c-q1-v1.1.1",
        "target_branch": TARGET_BRANCH,
        "target_commit_sha": target_commit,
        "implementation_base_commit_sha": implementation_commit,
        "historical_run": run_dir.name,
        "problem_id": "2024-C",
        "subproblem_id": "Q1",
        "sections": ["result_analysis", "model_boundary"],
        "humanization_noop_confirmed_on_target_commit": True,
        "production_baseline_blocked_until_target_integration": True,
        "files": [
            {
                "path": relative_posix(path, ROOT),
                "sha256": sha256_file(path),
            }
            for path in tracked
        ],
    }
    write_json(baseline_dir / "baseline_lock.json", lock)
    report = f"""# 论文写作编译器第一阶段基线

- 试点：2024-C 问题一
- 历史运行：`{run_dir.name}`
- 章节：结果分析、模型边界
- 目标资格提交：`{target_commit}`
- 当前实现基准提交：`{implementation_commit}`（本轮改动尚未提交）
- Claim：`C001`、`C002`
- 卡片来源题与试点题不同

目标提交上的 Humanization 自比较已经确认，但本工作树未切换到该分支。正式生产接入仍等待目标资格边界稳定；事实投影、Candidate 编译和故障注入不受此边界阻塞。
"""
    write_text(ROOT / "docs/reports/PAPER_COMPILER_BASELINE_V1_1_1.md", report)
    return lock


def build_manifest(
    evidence_dir: Path,
    automated_status: str,
    qualification_status: str,
    qualification_boundary_path: Path,
    review_freeze_path: Path,
) -> dict[str, Any]:
    paths = sorted(
        path
        for path in evidence_dir.rglob("*")
        if path.is_file() and path.name != "pilot_manifest.json"
    )
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_pilot_manifest",
        "pilot_id": "paper-compiler-2024c-q1-v1.1.1",
        "automated_status": automated_status,
        "automated_scope": "paper_compiler_v1_1_1_pilot",
        "qualification_status": qualification_status,
        "production_allowed": False,
        "validation_boundary": {
            "path": relative_posix(qualification_boundary_path, ROOT),
            "sha256": sha256_file(qualification_boundary_path),
        },
        "review_freeze": {
            "path": relative_posix(review_freeze_path, ROOT),
            "sha256": sha256_file(review_freeze_path),
        },
        "artifacts": [
            {"path": relative_posix(path, ROOT), "sha256": sha256_file(path)} for path in paths
        ],
    }
    validate_schema(manifest, "paper_compiler_pilot_manifest.schema.json")
    write_json(evidence_dir / "current/pilot_manifest.json", manifest)
    return manifest


def build_pilot() -> dict[str, Any]:
    run_dir = ROOT / RUN_RELATIVE
    evidence_dir = ROOT / EVIDENCE_RELATIVE
    baseline_dir = evidence_dir / "baseline"
    current_dir = evidence_dir / "current"
    card_dir = ROOT / CARD_RELATIVE
    bindings_path = baseline_dir / "claim_bindings.json"
    graph_path = baseline_dir / "argument_graph.json"
    projection_path = current_dir / "paper_fact_projection.json"
    bundle_path = current_dir / "rhetoric_bundle.json"

    build_baseline_lock(run_dir, baseline_dir)
    projection = build_projection(run_dir, bindings_path, "Q1")
    write_json(projection_path, projection)
    projection_report = validate_projection(projection_path, run_dir)
    write_json(current_dir / "paper_fact_projection_report.json", projection_report)
    bundle = build_bundle(card_dir, bundle_path)
    retrieval = retrieve_cards(
        baseline_dir / "plan_c.json",
        projection_path,
        card_dir,
        bundle_path,
    )
    write_json(current_dir / "rhetoric_retrieval_report.json", retrieval)

    render_reports = []
    for label in ("b", "c"):
        plan_path = baseline_dir / f"plan_{label}.json"
        annotated = current_dir / f"version_{label}_annotated.md"
        clean = current_dir / f"version_{label}.md"
        report = render_plan(
            plan_path,
            projection_path,
            graph_path,
            annotated,
            clean,
            current_dir / f"version_{label}_render_report.json",
            card_dir if label == "c" else None,
            bundle_path if label == "c" else None,
        )
        exemptions_path = current_dir / f"version_{label}_typed_exemptions.json"
        write_json(exemptions_path, parse_exemptions(annotated))
        fact_report = validate_realization(annotated, projection_path, exemptions_path)
        write_json(current_dir / f"version_{label}_fact_report.json", fact_report)
        render_reports.extend([report, fact_report])

    overlap = check_overlap(
        card_dir,
        ROOT / SOURCE_TEXT_RELATIVE,
        current_dir / "version_c.md",
    )
    write_json(current_dir / "rhetoric_overlap_report.json", overlap)

    faults = run_fault_injections(
        current_dir / "version_c_annotated.md",
        projection_path,
        baseline_dir / "plan_c.json",
        graph_path,
        card_dir,
        bundle_path,
        evidence_dir / "fault_injection",
    )
    review_dir = evidence_dir / "exploratory_ab"
    qualification_boundary_path = current_dir / "qualification_boundary_report.json"
    review_freeze_path = review_dir / "review_freeze_manifest.json"
    if not review_freeze_path.exists():
        collect_qualification_boundary(qualification_boundary_path)
    elif not qualification_boundary_path.exists():
        raise FileNotFoundError("评审已冻结，但资格边界报告缺失")
    qualification_boundary = load_json(qualification_boundary_path)
    validate_schema(
        qualification_boundary,
        "paper_compiler_qualification_boundary.schema.json",
    )
    build_review_freeze(
        baseline_dir,
        current_dir,
        review_dir,
        qualification_boundary_path,
    )
    review_status = validate_reviews(review_dir, review_dir / "status.json")
    automated_passed = (
        projection_report["status"] == "passed"
        and overlap["status"] == "automatic_passed"
        and retrieval["status"] == "passed"
        and all(report["status"] == "passed" for report in render_reports)
        and faults["status"] == "passed"
        and bundle["production_allowed"] is False
        and qualification_boundary["automated_status"] == "passed"
        and review_status["integrity_status"] == "passed"
    )
    manifest = build_manifest(
        evidence_dir,
        "passed" if automated_passed else "failed",
        review_status["status"],
        qualification_boundary_path,
        review_freeze_path,
    )
    return {
        "automated_status": manifest["automated_status"],
        "qualification_status": review_status["status"],
        "fault_cases_caught": faults["cases_caught"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建论文写作编译器 v1.1.1 第一阶段试点")
    parser.parse_args()
    summary = build_pilot()
    print(summary)
    return 0 if summary["automated_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
