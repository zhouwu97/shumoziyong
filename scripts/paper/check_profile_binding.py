from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} 不存在：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象：{path}")
    return value


def validate_profile(profile: dict[str, Any]) -> None:
    schema = load_json_object(ROOT / "schemas" / "paper_profile.schema.json", "paper profile schema")
    Draft202012Validator(schema).validate(profile)


def check_profile_binding(
    *,
    paper_kind: str,
    profile_path: Path | None = None,
    declared_profile_id: str | None = None,
    renderer_id: str | None = None,
    renderer_version: str | None = None,
    template_id: str | None = None,
    template_dir: Path | None = None,
) -> dict[str, Any]:
    """检查文档类型与 Profile/renderer/template 的显式绑定。"""
    if paper_kind not in {"submission_paper", "technical_report"}:
        raise ValueError(f"不支持的 paper_kind：{paper_kind!r}")

    if paper_kind == "technical_report":
        return {
            "schema_version": "1.0.0",
            "paper_kind": paper_kind,
            "constraints_applied": False,
            "passed": True,
            "issues": [],
        }

    issues: list[dict[str, str]] = []

    def fail(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    if profile_path is None:
        fail("profile_not_declared", "submission_paper 必须声明 paper profile")
        profile: dict[str, Any] | None = None
    else:
        try:
            profile = load_json_object(profile_path, "paper profile")
            validate_profile(profile)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            fail("invalid_profile", str(exc))
            profile = None
        except Exception as exc:  # jsonschema 提供精确字段路径。
            fail("invalid_profile", f"paper profile 不符合 schema：{exc}")
            profile = None

    for value, code, message in (
        (declared_profile_id, "profile_id_not_declared", "submission_paper 必须声明 profile_id"),
        (renderer_id, "renderer_not_declared", "submission_paper 必须声明 renderer_id"),
        (renderer_version, "renderer_version_not_declared", "submission_paper 必须声明 renderer 版本"),
        (template_id, "template_not_declared", "submission_paper 必须声明 template_id"),
    ):
        if not isinstance(value, str) or not value.strip():
            fail(code, message)

    if template_dir is None or not template_dir.is_dir():
        fail("approved_template_missing", "批准模板目录不存在，只阻断 submission rendering")
        template_manifest: dict[str, Any] | None = None
    else:
        try:
            template_manifest = load_json_object(template_dir / "template.json", "template manifest")
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            fail("invalid_template_manifest", str(exc))
            template_manifest = None

    if profile is not None:
        actual_profile_id = profile.get("profile_id")
        if declared_profile_id and declared_profile_id != actual_profile_id:
            fail(
                "profile_id_mismatch",
                f"声明的 profile_id={declared_profile_id!r} 与 Profile 不一致",
            )
        approved = {
            (item.get("id"), item.get("template_id"))
            for item in profile.get("approved_renderers", [])
            if isinstance(item, dict)
        }
        if renderer_id and template_id and (renderer_id, template_id) not in approved:
            fail(
                "renderer_template_not_approved",
                f"Profile 未批准 renderer/template 组合：{renderer_id}/{template_id}",
            )

    if template_manifest is not None:
        if template_manifest.get("template_id") != template_id:
            fail("template_id_mismatch", "模板 manifest 的 template_id 与声明不一致")
        if template_manifest.get("renderer_id") != renderer_id:
            fail("template_renderer_mismatch", "模板 manifest 的 renderer_id 与声明不一致")

    return {
        "schema_version": "1.0.0",
        "paper_kind": paper_kind,
        "constraints_applied": True,
        "profile_id": declared_profile_id,
        "renderer_id": renderer_id,
        "renderer_version": renderer_version,
        "template_id": template_id,
        "passed": not issues,
        "issues": issues,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查论文类型与 Profile/renderer/template 绑定")
    parser.add_argument("--paper-kind", required=True, choices=("submission_paper", "technical_report"))
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--profile-id")
    parser.add_argument("--renderer-id")
    parser.add_argument("--renderer-version")
    parser.add_argument("--template-id")
    parser.add_argument("--template-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("profile_binding_report.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = check_profile_binding(
        paper_kind=args.paper_kind,
        profile_path=args.profile,
        declared_profile_id=args.profile_id,
        renderer_id=args.renderer_id,
        renderer_version=args.renderer_version,
        template_id=args.template_id,
        template_dir=args.template_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "issues": len(report["issues"])}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
