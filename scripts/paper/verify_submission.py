from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from .check_claim_bindings import check_bindings
    from .check_paper_source import check_paper_source, collect_sources, sha256_file, strip_comments
    from .check_profile_binding import check_profile_binding
    from .check_pdf_metadata import check_pdf_metadata
    from .rasterize_pdf import rasterize_pdf
except ImportError:  # 允许直接执行脚本。
    from check_claim_bindings import check_bindings
    from check_paper_source import check_paper_source, collect_sources, sha256_file, strip_comments
    from check_profile_binding import check_profile_binding
    from check_pdf_metadata import check_pdf_metadata
    from rasterize_pdf import rasterize_pdf


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SECTION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("摘要", ("摘要",)),
    ("问题重述", ("问题重述", "问题背景")),
    ("问题分析", ("问题分析",)),
    ("模型假设", ("模型假设", "基本假设")),
    ("符号说明", ("符号说明", "符号约定")),
    ("模型建立", ("模型建立", "模型构建", "离散事件模型")),
    ("模型求解", ("模型求解", "算法设计", "求解方法")),
    ("结果分析", ("结果分析", "结果与分析", "结果与机理分析")),
    ("模型检验", ("模型检验", "模型验证")),
    ("模型评价", ("模型评价", "模型的评价", "优缺点")),
    ("结论", ("结论", "总结")),
    ("参考文献", ("参考文献",)),
)
FORMULA_CODES = {
    "complex_formula_as_plain_text",
    "critical_formula_missing_label",
    "missing_equation_label",
}
INTERNAL_CODES = {
    "internal_results_path",
    "internal_training_path",
    "internal_json_name",
    "internal_workflow_script",
    "internal_gate_name",
}


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} 不存在：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象：{path}")
    return value


def load_schema(name: str) -> dict[str, Any]:
    return load_json_object(ROOT / "schemas" / name, name)


def validate_payload(payload: dict[str, Any], schema_name: str) -> list[str]:
    validator = Draft202012Validator(load_schema(schema_name))
    return [error.message for error in sorted(validator.iter_errors(payload), key=str)]


def check(status: bool, issues: list[str] | None = None) -> dict[str, Any]:
    return {"status": "passed" if status else "failed", "issues": issues or []}


def all_source_text(main_path: Path) -> str:
    chunks: list[str] = []
    for path in collect_sources(main_path):
        if path.is_file():
            chunks.append(strip_comments(path.read_text(encoding="utf-8"), path.suffix))
    return "\n".join(chunks)


def check_sections(text: str) -> list[str]:
    issues: list[str] = []
    for label, alternatives in REQUIRED_SECTION_GROUPS:
        if not any(alternative in text for alternative in alternatives):
            issues.append(f"缺少论文结构章节：{label}")
    return issues


def check_references(text: str) -> list[str]:
    issues: list[str] = []
    if "参考文献" not in text:
        issues.append("缺少参考文献章节")
    has_citation = bool(re.search(r"\[\d+(?:\s*[-,，]\s*\d+)*\]|@ref[-_:][A-Za-z0-9_.:-]+", text))
    if not has_citation:
        issues.append("正文未发现可追踪文献引用")
    has_entry = "#reference-entry" in text or bool(
        re.search(r"^\s*\[\d+\]\s*\S+", text, flags=re.MULTILINE)
    )
    if not has_entry:
        issues.append("参考文献章节未发现结构化条目")
    return issues


def verify_manifest_files(manifest: dict[str, Any], root: Path, label: str) -> list[str]:
    issues: list[str] = []
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return [f"{label} 缺少 files 清单"]
    for item in files:
        if not isinstance(item, dict):
            issues.append(f"{label} 包含非法文件记录")
            continue
        relative = Path(str(item.get("path", "")))
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            issues.append(f"{label} 文件越出根目录：{relative.as_posix()}")
            continue
        if not target.is_file():
            issues.append(f"{label} 文件不存在：{relative.as_posix()}")
            continue
        if sha256_file(target) != item.get("sha256"):
            issues.append(f"{label} 文件哈希不匹配：{relative.as_posix()}")
    return issues


def verify_render_attestation(
    *,
    attestation_path: Path,
    profile_path: Path,
    template_dir: Path,
    source_dir: Path,
) -> tuple[dict[str, Any], Path | None, list[str]]:
    issues: list[str] = []
    try:
        attestation = load_json_object(attestation_path, "render attestation")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return {}, None, [str(exc)]
    issues.extend(validate_payload(attestation, "paper_render_attestation.schema.json"))
    base = attestation_path.parent
    artifact_fields = (
        ("source_manifest", "source_manifest_sha256"),
        ("profile_snapshot", "profile_snapshot_sha256"),
        ("template_manifest", "template_manifest_sha256"),
        ("output_pdf", "output_pdf_sha256"),
    )
    resolved: dict[str, Path] = {}
    for path_field, hash_field in artifact_fields:
        target = (base / str(attestation.get(path_field, ""))).resolve()
        resolved[path_field] = target
        if not target.is_file():
            issues.append(f"render attestation 绑定文件不存在：{path_field}")
        elif sha256_file(target) != attestation.get(hash_field):
            issues.append(f"render attestation 绑定哈希不匹配：{path_field}")

    if resolved.get("profile_snapshot", Path()).is_file():
        try:
            if load_json_object(resolved["profile_snapshot"], "profile snapshot") != load_json_object(
                profile_path, "paper profile"
            ):
                issues.append("Profile snapshot 与当前批准 Profile 不一致")
        except (ValueError, json.JSONDecodeError) as exc:
            issues.append(str(exc))
    if resolved.get("source_manifest", Path()).is_file():
        manifest = load_json_object(resolved["source_manifest"], "source manifest")
        issues.extend(verify_manifest_files(manifest, source_dir, "source manifest"))
    if resolved.get("template_manifest", Path()).is_file():
        manifest = load_json_object(resolved["template_manifest"], "template manifest")
        issues.extend(verify_manifest_files(manifest, template_dir, "template manifest"))
    return attestation, resolved.get("output_pdf"), issues


def verify_visual_review(
    review_path: Path, *, pdf_sha256: str, page_count: int
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    try:
        review = load_json_object(review_path, "visual review")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return {}, [str(exc)]
    issues.extend(validate_payload(review, "paper_visual_review.schema.json"))
    if review.get("pdf_sha256") != pdf_sha256:
        issues.append("视觉验收绑定的 PDF SHA-256 不匹配")
    if review.get("page_count") != page_count:
        issues.append("视觉验收记录页数与 PDF 不一致")
    expected_pages = set(range(1, page_count + 1))
    reviewed_pages = set(review.get("reviewed_pages", []))
    if reviewed_pages != expected_pages:
        issues.append("视觉验收未逐页覆盖全部 PDF 页面")
    for item in review.get("issues", []):
        if item.get("severity") in {"P0", "P1"} and item.get("status") == "open":
            issues.append(f"仍有未关闭的 {item['severity']} 视觉问题：{item['issue']}")
    if review.get("status") != "passed":
        issues.append("视觉验收状态不是 passed")
    return review, issues


def artifact(path: Path, role: str) -> dict[str, str]:
    return {"role": role, "path": str(path.resolve()), "sha256": sha256_file(path)}


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = ["# Submission Verity 报告", "", f"结论：**{report['status'].upper()}**", ""]
    for name, result in report["checks"].items():
        lines.append(f"- {name}: {result['status'].upper()}")
        lines.extend(f"  - {issue}" for issue in result["issues"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_submission(
    *,
    main_path: Path,
    profile_path: Path,
    template_dir: Path,
    render_attestation_path: Path,
    humanization_report_path: Path,
    claim_bindings_path: Path,
    claims_project_root: Path,
    model_consistency_path: Path,
    visual_review_path: Path,
    reports_dir: Path,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    source_report = check_paper_source(main_path)
    source_text = all_source_text(main_path)
    source_failures = [
        issue for issue in source_report["issues"] if issue.get("severity") == "FAIL"
    ]

    attestation, pdf_path, attestation_issues = verify_render_attestation(
        attestation_path=render_attestation_path,
        profile_path=profile_path,
        template_dir=template_dir,
        source_dir=main_path.parent,
    )
    binding_report = check_profile_binding(
        paper_kind="submission_paper",
        profile_path=profile_path,
        declared_profile_id=attestation.get("profile_id"),
        renderer_id=attestation.get("renderer_id"),
        renderer_version=attestation.get("renderer_version"),
        template_id=attestation.get("template_id"),
        template_dir=template_dir,
    )

    humanization = load_json_object(humanization_report_path, "humanization report")
    humanization_issues = validate_payload(
        humanization, "paper_humanization_report.schema.json"
    )
    if humanization.get("status") != "passed":
        humanization_issues.append("Humanizer 差分状态不是 passed")
    if humanization.get("output_sha256") != sha256_file(main_path):
        humanization_issues.append("Humanizer 输出哈希与最终论文入口不匹配")

    claim_report = check_bindings(claim_bindings_path, main_path, claims_project_root)
    model_consistency = load_json_object(model_consistency_path, "model-text consistency")
    model_issues = validate_payload(
        model_consistency, "model_text_consistency_report.schema.json"
    )
    if model_consistency.get("status") != "passed":
        model_issues.append("模型、代码、结果与论文一致性状态不是 passed")
    if model_consistency.get("paper_source_sha256") != sha256_file(main_path):
        model_issues.append("一致性报告绑定的论文入口哈希不匹配")
    for path_field, hash_field in (
        ("model_route", "model_route_sha256"),
        ("result_report", "result_report_sha256"),
    ):
        bound_path = (model_consistency_path.parent / str(model_consistency.get(path_field, ""))).resolve()
        if not bound_path.is_file():
            model_issues.append(f"一致性报告绑定文件不存在：{path_field}")
        elif sha256_file(bound_path) != model_consistency.get(hash_field):
            model_issues.append(f"一致性报告绑定哈希不匹配：{path_field}")

    pdf_metadata: dict[str, Any] = {"passed": False, "issues": []}
    raster_report: dict[str, Any] = {}
    visual_issues = ["缺少可验证的 submission PDF"]
    visual_review: dict[str, Any] = {}
    if pdf_path is not None and pdf_path.is_file():
        pages_dir = reports_dir / "pages"
        try:
            raster_report = rasterize_pdf(pdf_path, pages_dir)
            pdf_metadata = check_pdf_metadata(pdf_path, pages_dir)
            visual_review, visual_issues = verify_visual_review(
                visual_review_path,
                pdf_sha256=sha256_file(pdf_path),
                page_count=int(pdf_metadata.get("page_count", 0)),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            pdf_metadata = {"passed": False, "issues": [{"message": str(exc)}]}
            visual_issues = [str(exc)]

    formula_issues = [str(item["message"]) for item in source_failures if item["code"] in FORMULA_CODES]
    internal_issues = [str(item["message"]) for item in source_failures if item["code"] in INTERNAL_CODES]
    other_source_issues = [
        str(item["message"])
        for item in source_failures
        if item["code"] not in FORMULA_CODES | INTERNAL_CODES
    ]
    section_issues = check_sections(source_text) + other_source_issues
    reference_issues = check_references(source_text)
    metadata_issues = [str(item.get("message", item)) for item in pdf_metadata.get("issues", [])]
    raster_issues: list[str] = []
    if not raster_report or int(raster_report.get("page_count", 0)) < 1:
        raster_issues.append("PDF 未成功逐页栅格化")

    checks = {
        "profile_binding": check(
            bool(binding_report["passed"]),
            [str(item["message"]) for item in binding_report["issues"]],
        ),
        "render_attestation": check(not attestation_issues, attestation_issues),
        "humanization_diff": check(not humanization_issues, humanization_issues),
        "section_structure": check(not section_issues, section_issues),
        "formula_environment": check(not formula_issues, formula_issues),
        "claim_binding": check(
            bool(claim_report["passed"]),
            [str(item["message"]) for item in claim_report["issues"]],
        ),
        "model_text_consistency": check(not model_issues, model_issues),
        "internal_term_leakage": check(not internal_issues, internal_issues),
        "references": check(not reference_issues, reference_issues),
        "compile_result": check(
            bool(attestation.get("compiled")) and pdf_path is not None and pdf_path.is_file(),
            [] if attestation.get("compiled") else ["render attestation 未确认编译成功"],
        ),
        "pdf_metadata": check(bool(pdf_metadata.get("passed")), metadata_issues),
        "pdf_rasterization": check(not raster_issues, raster_issues),
        "visual_review_record": check(not visual_issues, visual_issues),
    }
    failures = sum(result["status"] == "failed" for result in checks.values())
    warnings = int(source_report["summary"].get("warnings", 0)) + sum(
        item.get("severity") == "WARN" for item in pdf_metadata.get("issues", [])
    )
    artifact_paths = {
        "paper_source": main_path,
        "render_attestation": render_attestation_path,
        "humanization_report": humanization_report_path,
        "claim_bindings": claim_bindings_path,
        "model_text_consistency": model_consistency_path,
        "visual_review": visual_review_path,
    }
    if pdf_path is not None and pdf_path.is_file():
        artifact_paths["submission_pdf"] = pdf_path
    report = {
        "schema_version": "1.0.0",
        "paper_kind": "submission_paper",
        "profile_id": str(attestation.get("profile_id", "unknown")),
        "template_id": str(attestation.get("template_id", "unknown")),
        "renderer_id": str(attestation.get("renderer_id", "unknown")),
        "status": "failed" if failures else "passed",
        "checks": checks,
        "artifacts": [artifact(path, role) for role, path in artifact_paths.items()],
        "summary": {
            "passed": len(checks) - failures,
            "failed": failures,
            "warnings": warnings,
        },
    }
    Draft202012Validator(load_schema("paper_verify_report.schema.json")).validate(report)
    report_path = reports_dir / "paper_verify_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(reports_dir / "VERIFY_REPORT.md", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一执行 submission paper 的 Verity 预检")
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--render-attestation", type=Path, required=True)
    parser.add_argument("--humanization-report", type=Path, required=True)
    parser.add_argument("--claim-bindings", type=Path, required=True)
    parser.add_argument("--claims-project-root", type=Path, required=True)
    parser.add_argument("--model-consistency", type=Path, required=True)
    parser.add_argument("--visual-review", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = verify_submission(
        main_path=args.main,
        profile_path=args.profile,
        template_dir=args.template_dir,
        render_attestation_path=args.render_attestation,
        humanization_report_path=args.humanization_report,
        claim_bindings_path=args.claim_bindings,
        claims_project_root=args.claims_project_root,
        model_consistency_path=args.model_consistency,
        visual_review_path=args.visual_review,
        reports_dir=args.reports_dir,
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
