from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
STAGE_FILES: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "upstream_compatible_precheck",
        (
            (
                "paper_external_precheck_report.json",
                "paper_external_precheck_report",
                "paper_external_precheck_report.schema.json",
            ),
            ("suggested_repairs.json", "suggested_repairs", "suggested_repairs.schema.json"),
        ),
    ),
    (
        "local_evidence_validation",
        (
            ("paper_claim_map.json", "paper_claim_map", "gate_business_artifact.schema.json"),
            (
                "model_text_consistency_report.json",
                "model_text_consistency_report",
                "model_text_consistency_report.schema.json",
            ),
        ),
    ),
    (
        "template_render_visual",
        (
            ("template_selection.json", "template_selection", "template_selection.schema.json"),
            (
                "paper_template_manifest.json",
                "paper_template_manifest",
                "paper_template_manifest.schema.json",
            ),
            (
                "paper_render_attestation.json",
                "paper_render_attestation",
                "paper_render_attestation.schema.json",
            ),
            ("paper_verify_report.json", "paper_verify_report", "paper_verify_report.schema.json"),
            ("paper_visual_review.json", "paper_visual_review", "paper_visual_review.schema.json"),
            ("submission.pdf", "submission_pdf", ""),
        ),
    ),
)


class PaperProductionManifestError(ValueError):
    """论文生产证据无法形成一致、可审计的最终清单。"""


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {label}：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PaperProductionManifestError(f"{label} 必须是 JSON 对象")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_payload(payload: dict[str, Any], schema_name: str, label: str) -> None:
    schema = load_json_object(ROOT / "schemas" / schema_name, f"Schema {schema_name}")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise PaperProductionManifestError(f"{label} 不符合 Schema：{details}")


def _artifact_record(artifact_root: Path, filename: str, role: str) -> dict[str, Any]:
    path = (artifact_root / filename).resolve()
    try:
        relative = path.relative_to(artifact_root.resolve()).as_posix()
    except ValueError as exc:
        raise PaperProductionManifestError(f"产物越出论文证据目录：{filename}") from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise PaperProductionManifestError(f"论文生产产物不存在或为空：{filename}")
    return {
        "role": role,
        "path": relative,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _load_stage_payloads(artifact_root: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for _stage, files in STAGE_FILES:
        for filename, role, schema_name in files:
            path = artifact_root / filename
            if path.suffix == ".pdf":
                if not path.is_file() or not path.read_bytes().startswith(b"%PDF-"):
                    raise PaperProductionManifestError("submission.pdf 缺少合法 PDF 文件头")
                continue
            payload = load_json_object(path, role)
            if schema_name:
                validate_payload(payload, schema_name, filename)
            payloads[role] = payload
    return payloads


def _stage_statuses(payloads: Mapping[str, dict[str, Any]], artifact_root: Path) -> tuple[bool, bool, bool]:
    precheck = payloads["paper_external_precheck_report"]
    repairs = payloads["suggested_repairs"]
    precheck_passed = (
        precheck.get("status") == "passed"
        and precheck.get("mutation_detected") is False
        and repairs.get("repairs") == []
        and precheck.get("suggested_repairs", {}).get("sha256")
        == sha256_file(artifact_root / "suggested_repairs.json")
    )

    consistency = payloads["model_text_consistency_report"]
    local_passed = consistency.get("status") == "passed"

    render = payloads["paper_render_attestation"]
    verify = payloads["paper_verify_report"]
    visual = payloads["paper_visual_review"]
    pdf_sha = sha256_file(artifact_root / "submission.pdf")
    production_passed = (
        render.get("compiled") is True
        and render.get("output_pdf_sha256") == pdf_sha
        and verify.get("status") == "passed"
        and visual.get("status") == "passed"
        and visual.get("pdf_sha256") == pdf_sha
    )
    return precheck_passed, local_passed, production_passed


def build_paper_production_manifest(
    artifact_root: Path,
    binding: Mapping[str, str],
) -> dict[str, Any]:
    """按固定三阶段顺序聚合证据；本清单不授予 Gate 4 PASS。"""
    artifact_root = artifact_root.resolve()
    payloads = _load_stage_payloads(artifact_root)
    claim_map = payloads["paper_claim_map"]
    for field, expected in binding.items():
        if claim_map.get(field) != expected:
            raise PaperProductionManifestError(f"paper_claim_map.{field} 与当前 Run 绑定不一致")
    stage_passed = _stage_statuses(payloads, artifact_root)
    stages: list[dict[str, Any]] = []
    for sequence, ((stage_name, files), passed) in enumerate(
        zip(STAGE_FILES, stage_passed, strict=True),
        1,
    ):
        stages.append(
            {
                "sequence": sequence,
                "stage": stage_name,
                "status": "passed" if passed else "failed",
                "artifacts": [
                    _artifact_record(artifact_root, filename, role)
                    for filename, role, _schema_name in files
                ],
            }
        )
    submission_eligible = all(stage_passed)
    selection = payloads["template_selection"]
    manifest = {
        "schema_version": "2.0.0",
        "artifact_type": "paper_production_manifest_v2",
        **binding,
        "paper_kind": "submission_paper" if submission_eligible else "technical_report",
        "template_selection": {
            "logical_key": selection["logical_key"],
            "template_id": selection["template_id"],
            "engine": selection["engine"],
            "selection_source": selection["selection_source"],
            "source_tree_sha256": selection["source_tree_sha256"],
            "overlay_id": selection["overlay_id"],
            "upstream_default_overridden": selection["upstream_default_overridden"],
        },
        "stages": stages,
        "authority": {
            "external_precheck_can_decide_gate4_pass": False,
            "manifest_grants_gate4_pass": False,
        },
        "status": "submission_candidate" if submission_eligible else "technical_report_only",
        "submission_eligible": submission_eligible,
    }
    validate_payload(
        manifest,
        "paper_production_manifest_v2.schema.json",
        "paper_production_manifest_v2",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="构建 paper_production_manifest_v2")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--problem-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--runtime-pack-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = build_paper_production_manifest(
        args.artifact_root,
        {
            "run_id": args.run_id,
            "problem_id": args.problem_id,
            "profile": args.profile,
            "runtime_version": args.runtime_version,
            "runtime_pack_sha256": args.runtime_pack_sha256,
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": manifest["status"]}, ensure_ascii=False))
    return 0 if manifest["submission_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
