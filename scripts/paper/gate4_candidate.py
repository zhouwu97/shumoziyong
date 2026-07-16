from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

try:
    from atomic_io import atomic_write_bytes
except ImportError:  # pragma: no cover - 允许从仓库根目录直接执行。
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from atomic_io import atomic_write_bytes

try:
    from .paper_production_manifest import build_paper_production_manifest
except ImportError:  # pragma: no cover - 允许直接执行脚本。
    from paper_production_manifest import build_paper_production_manifest


ROOT = Path(__file__).resolve().parents[2]
PAPER_PIPELINE_CONTRACT_VERSION = "1.0.0"
PAPER_CANDIDATE_STATUS = "paper_candidate_ready_for_independent_review"

PAPER_CANDIDATE_ARTIFACTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "paper_external_precheck_report.json",
        "paper_external_precheck_report",
        "application/json",
        "paper_external_precheck_report.schema.json",
    ),
    (
        "suggested_repairs.json",
        "suggested_repairs",
        "application/json",
        "suggested_repairs.schema.json",
    ),
    (
        "paper_claim_map.json",
        "paper_claim_map",
        "application/json",
        "gate_business_artifact.schema.json",
    ),
    (
        "model_text_consistency_report.json",
        "model_text_consistency_report",
        "application/json",
        "model_text_consistency_report.schema.json",
    ),
    (
        "paper_narrative_report.json",
        "paper_narrative_report",
        "application/json",
        "paper_narrative_report.schema.json",
    ),
    (
        "paper_profile.snapshot.json",
        "paper_profile_snapshot",
        "application/json",
        "paper_profile.schema.json",
    ),
    (
        "template_selection.json",
        "template_selection",
        "application/json",
        "template_selection.schema.json",
    ),
    (
        "paper_template_manifest.json",
        "paper_template_manifest",
        "application/json",
        "paper_template_manifest.schema.json",
    ),
    (
        "paper_render_attestation.json",
        "paper_render_attestation",
        "application/json",
        "paper_render_attestation.schema.json",
    ),
    (
        "paper_humanization_report.json",
        "paper_humanization_report",
        "application/json",
        "paper_humanization_report.schema.json",
    ),
    (
        "paper_verify_report.json",
        "paper_verify_report",
        "application/json",
        "paper_verify_report.schema.json",
    ),
    (
        "paper_source_manifest.json",
        "paper_source_manifest",
        "application/json",
        "paper_source_manifest.schema.json",
    ),
    (
        "paper_visual_review.json",
        "paper_visual_review",
        "application/json",
        "paper_visual_review.schema.json",
    ),
    ("submission.pdf", "submission_pdf", "application/pdf", ""),
    (
        "paper_production_manifest_v2.json",
        "paper_production_manifest_v2",
        "application/json",
        "paper_production_manifest_v2.schema.json",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {label}：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return value


def validate_schema(payload: dict[str, Any], schema_name: str, label: str) -> None:
    schema = load_json_object(ROOT / "schemas" / schema_name, f"Schema {schema_name}")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"{label} 不符合 Schema：{details}")


def _records_by_role(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    roles = [str(record.get("role", "")) for record in records]
    if len(roles) != len(set(roles)):
        raise ValueError(f"{label} 存在重复 role")
    return {role: record for role, record in zip(roles, records, strict=True)}


def _source_entry_sha(source_manifest: Mapping[str, Any]) -> str:
    entry = str(source_manifest["entry"])
    matches = [item for item in source_manifest["files"] if item.get("path") == entry]
    if len(matches) != 1:
        raise ValueError("paper_source_manifest 的 entry 必须且只能对应一个文件记录")
    paths = [str(item.get("path", "")) for item in source_manifest["files"]]
    if len(paths) != len(set(paths)):
        raise ValueError("paper_source_manifest.files 存在重复路径")
    return str(matches[0]["sha256"])


def _require_passed_reports(
    profile: Mapping[str, Any],
    template: Mapping[str, Any],
    attestation: Mapping[str, Any],
    humanization: Mapping[str, Any],
    verify_report: Mapping[str, Any],
    model_consistency: Mapping[str, Any],
    narrative_report: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    visual_review: Mapping[str, Any],
    production_manifest: Mapping[str, Any],
    run_dir: Path,
) -> None:
    if not attestation.get("compiled"):
        raise ValueError("paper_render_attestation.compiled 必须为 true")
    if humanization.get("status") != "passed":
        raise ValueError("paper_humanization_report.status 必须为 passed")
    if model_consistency.get("status") != "passed":
        raise ValueError("model_text_consistency_report.status 必须为 passed")
    if narrative_report.get("status") != "passed":
        raise ValueError("paper_narrative_report.status 必须为 passed")
    if narrative_report.get("submission_allowed") is not True:
        raise ValueError("paper_narrative_report.submission_allowed 必须为 true")
    if visual_review.get("status") != "passed":
        raise ValueError("paper_visual_review.status 必须为 passed")
    if verify_report.get("status") != "passed":
        raise ValueError("paper_verify_report.status 必须为 passed")
    if production_manifest.get("status") != "submission_candidate":
        raise ValueError("paper_production_manifest_v2.status 必须为 submission_candidate")
    if production_manifest.get("submission_eligible") is not True:
        raise ValueError("paper_production_manifest_v2.submission_eligible 必须为 true")
    failed_checks = [
        name
        for name, result in verify_report.get("checks", {}).items()
        if result.get("status") != "passed"
    ]
    if failed_checks:
        raise ValueError("paper_verify_report 仍有失败检查：" + ", ".join(failed_checks))
    summary = verify_report.get("summary", {})
    if summary.get("passed") != len(verify_report.get("checks", {})) or summary.get("failed") != 0:
        raise ValueError("paper_verify_report.summary 与逐项检查结果不一致")

    profile_id = profile.get("profile_id")
    if attestation.get("profile_id") != profile_id or verify_report.get("profile_id") != profile_id:
        raise ValueError("Profile snapshot、渲染证明与 VERIFY_REPORT 的 profile_id 不一致")
    if template.get("template_id") != attestation.get("template_id"):
        raise ValueError("模板清单与渲染证明的 template_id 不一致")
    if template.get("renderer_id") != attestation.get("renderer_id"):
        raise ValueError("模板清单与渲染证明的 renderer_id 不一致")
    if verify_report.get("template_id") != attestation.get("template_id"):
        raise ValueError("VERIFY_REPORT 与渲染证明的 template_id 不一致")
    if verify_report.get("renderer_id") != attestation.get("renderer_id"):
        raise ValueError("VERIFY_REPORT 与渲染证明的 renderer_id 不一致")

    expected_attestation_files = {
        "source_manifest": ("paper_source_manifest.json", "source_manifest_sha256"),
        "profile_snapshot": ("paper_profile.snapshot.json", "profile_snapshot_sha256"),
        "template_manifest": ("paper_template_manifest.json", "template_manifest_sha256"),
    }
    for path_field, (expected_path, hash_field) in expected_attestation_files.items():
        if attestation.get(path_field) != expected_path:
            raise ValueError(f"paper_render_attestation.{path_field} 必须为 {expected_path}")
        if attestation.get(hash_field) != sha256_file(run_dir / expected_path):
            raise ValueError(f"paper_render_attestation.{hash_field} 与当前文件不一致")
    if attestation.get("output_pdf_sha256") != sha256_file(run_dir / "submission.pdf"):
        raise ValueError("paper_render_attestation.output_pdf_sha256 与当前文件不一致")

    paper_source_sha = _source_entry_sha(source_manifest)
    if humanization.get("output_sha256") != paper_source_sha:
        raise ValueError("Humanizer 输出哈希与源码清单入口不一致")
    if model_consistency.get("paper_source_sha256") != paper_source_sha:
        raise ValueError("模型—正文一致性报告与源码清单入口不一致")
    for path_field, hash_field in (
        ("model_route", "model_route_sha256"),
        ("result_report", "result_report_sha256"),
    ):
        if model_consistency.get(path_field) != f"{path_field}.json":
            raise ValueError(f"model_text_consistency_report.{path_field} 必须绑定当前 Run 根目录文件")
        if model_consistency.get(hash_field) != sha256_file(run_dir / f"{path_field}.json"):
            raise ValueError(f"model_text_consistency_report.{hash_field} 与当前 Run 文件不一致")

    pdf_sha = sha256_file(run_dir / "submission.pdf")
    if visual_review.get("pdf_sha256") != pdf_sha:
        raise ValueError("视觉验收记录与 submission.pdf 哈希不一致")
    expected_pages = set(range(1, int(visual_review["page_count"]) + 1))
    if set(visual_review.get("reviewed_pages", [])) != expected_pages:
        raise ValueError("视觉验收记录未逐页覆盖 submission.pdf")
    if any(
        item.get("severity") in {"P0", "P1"} and item.get("status") == "open"
        for item in visual_review.get("issues", [])
    ):
        raise ValueError("视觉验收记录仍有未关闭的 P0/P1 问题")

    verify_artifacts = _records_by_role(list(verify_report["artifacts"]), "paper_verify_report.artifacts")
    expected_verify_hashes = {
        "render_attestation": sha256_file(run_dir / "paper_render_attestation.json"),
        "humanization_report": sha256_file(run_dir / "paper_humanization_report.json"),
        "claim_bindings": sha256_file(run_dir / "paper_claim_map.json"),
        "model_text_consistency": sha256_file(
            run_dir / "model_text_consistency_report.json"
        ),
        "visual_review": sha256_file(run_dir / "paper_visual_review.json"),
        "submission_pdf": pdf_sha,
        "paper_source": paper_source_sha,
    }
    if set(verify_artifacts) != set(expected_verify_hashes):
        raise ValueError("paper_verify_report.artifacts 角色集合不完整或包含额外角色")
    for role, expected_hash in expected_verify_hashes.items():
        if verify_artifacts[role].get("sha256") != expected_hash:
            raise ValueError(f"paper_verify_report.artifacts[{role}] 哈希与当前候选证据不一致")


def validate_candidate_evidence(
    run_dir: Path, binding: Mapping[str, str] | None = None
) -> None:
    payloads: dict[str, dict[str, Any]] = {}
    for filename, role, media_type, schema_name in PAPER_CANDIDATE_ARTIFACTS:
        path = run_dir / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Gate 4 论文候选证据缺失或为空：{filename}")
        if media_type == "application/pdf":
            if not path.read_bytes().startswith(b"%PDF-"):
                raise ValueError("submission.pdf 缺少合法 PDF 文件头")
            continue
        payload = load_json_object(path, role)
        validate_schema(payload, schema_name, filename)
        payloads[role] = payload

    if binding is not None:
        claim_map = payloads["paper_claim_map"]
        for field, expected in binding.items():
            if claim_map.get(field) != expected:
                raise ValueError(f"paper_claim_map.json.{field} 与当前运行现场不一致")

    _require_passed_reports(
        payloads["paper_profile_snapshot"],
        payloads["paper_template_manifest"],
        payloads["paper_render_attestation"],
        payloads["paper_humanization_report"],
        payloads["paper_verify_report"],
        payloads["model_text_consistency_report"],
        payloads["paper_narrative_report"],
        payloads["paper_source_manifest"],
        payloads["paper_visual_review"],
        payloads["paper_production_manifest_v2"],
        run_dir,
    )
    if binding is not None:
        expected_production_manifest = build_paper_production_manifest(run_dir, binding)
        if payloads["paper_production_manifest_v2"] != expected_production_manifest:
            raise ValueError("paper_production_manifest_v2 与当前论文证据重建结果不一致")


def build_candidate_manifest(run_dir: Path, binding: Mapping[str, str]) -> dict[str, Any]:
    validate_candidate_evidence(run_dir, binding)
    artifacts = []
    for filename, role, media_type, _schema_name in PAPER_CANDIDATE_ARTIFACTS:
        path = run_dir / filename
        artifacts.append(
            {
                "path": filename,
                "role": role,
                "media_type": media_type,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_candidate_manifest",
        **binding,
        "candidate_status": PAPER_CANDIDATE_STATUS,
        "artifacts": artifacts,
    }
    validate_schema(manifest, "paper_candidate_manifest.schema.json", "paper_candidate_manifest.json")
    return manifest


def verify_candidate_manifest(run_dir: Path, binding: Mapping[str, str]) -> dict[str, Any]:
    manifest = load_json_object(run_dir / "paper_candidate_manifest.json", "paper candidate manifest")
    validate_schema(manifest, "paper_candidate_manifest.schema.json", "paper_candidate_manifest.json")
    for field, expected in binding.items():
        if manifest.get(field) != expected:
            raise ValueError(f"paper_candidate_manifest.json.{field} 与当前运行现场不一致")
    records = _records_by_role(list(manifest["artifacts"]), "paper_candidate_manifest.artifacts")
    expected_roles = {role for _filename, role, _media, _schema in PAPER_CANDIDATE_ARTIFACTS}
    if set(records) != expected_roles:
        raise ValueError("paper_candidate_manifest.artifacts 角色集合不完整或包含额外角色")
    for filename, role, media_type, _schema_name in PAPER_CANDIDATE_ARTIFACTS:
        record = records[role]
        path = run_dir / filename
        if record.get("path") != filename or record.get("media_type") != media_type:
            raise ValueError(f"paper_candidate_manifest.artifacts[{role}] 路径或媒体类型错误")
        if not path.is_file():
            raise ValueError(f"paper_candidate_manifest 引用文件不存在：{filename}")
        if record.get("sha256") != sha256_file(path) or record.get("size_bytes") != path.stat().st_size:
            raise ValueError(f"paper_candidate_manifest.artifacts[{role}] 内容哈希或大小不匹配")
    validate_candidate_evidence(run_dir, binding)
    return manifest


def _copy_input(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    atomic_write_bytes(target, source.read_bytes())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="暂存并绑定 Gate 4 论文候选证据")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--external-precheck", type=Path, required=True)
    parser.add_argument("--suggested-repairs", type=Path, required=True)
    parser.add_argument("--narrative-report", type=Path, required=True)
    parser.add_argument("--profile-snapshot", type=Path, required=True)
    parser.add_argument("--template-selection", type=Path, required=True)
    parser.add_argument("--template-manifest", type=Path, required=True)
    parser.add_argument("--render-attestation", type=Path, required=True)
    parser.add_argument("--humanization-report", type=Path, required=True)
    parser.add_argument("--verify-report", type=Path, required=True)
    parser.add_argument("--claim-map", type=Path)
    parser.add_argument("--model-consistency", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--visual-review", type=Path, required=True)
    parser.add_argument("--submission-pdf", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.run_dir.resolve()
    run_manifest = load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    runtime_manifest = load_json_object(
        run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json"
    )
    if run_manifest.get("paper_pipeline_contract_version") != PAPER_PIPELINE_CONTRACT_VERSION:
        raise ValueError("当前 Run 未启用 paper pipeline contract 1.0.0")
    sources = {
        "paper_external_precheck_report.json": args.external_precheck,
        "suggested_repairs.json": args.suggested_repairs,
        "paper_narrative_report.json": args.narrative_report,
        "paper_profile.snapshot.json": args.profile_snapshot,
        "template_selection.json": args.template_selection,
        "paper_template_manifest.json": args.template_manifest,
        "paper_render_attestation.json": args.render_attestation,
        "paper_humanization_report.json": args.humanization_report,
        "paper_verify_report.json": args.verify_report,
        "paper_claim_map.json": args.claim_map or run_dir / "paper_claim_map.json",
        "model_text_consistency_report.json": args.model_consistency,
        "paper_source_manifest.json": args.source_manifest,
        "paper_visual_review.json": args.visual_review,
        "submission.pdf": args.submission_pdf,
    }
    for filename, source in sources.items():
        _copy_input(source.resolve(), run_dir / filename)
    binding = {
        "run_id": str(run_manifest["run_id"]),
        "problem_id": str(run_manifest["problem_id"]),
        "profile": str(run_manifest["profile"]),
        "runtime_version": str(run_manifest["runtime_version"]),
        "runtime_pack_sha256": str(runtime_manifest["runtime_pack_sha256"]),
    }
    production_manifest = build_paper_production_manifest(run_dir, binding)
    atomic_write_bytes(
        run_dir / "paper_production_manifest_v2.json",
        (json.dumps(production_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    manifest = build_candidate_manifest(run_dir, binding)
    atomic_write_bytes(
        run_dir / "paper_candidate_manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({"status": manifest["candidate_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
