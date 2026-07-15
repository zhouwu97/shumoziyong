from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from .check_profile_binding import check_profile_binding, load_json_object
except ImportError:  # 允许直接执行脚本。
    from check_profile_binding import check_profile_binding, load_json_object


ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_file_manifest(root: Path, *, excluded: set[Path] | None = None) -> list[dict[str, Any]]:
    excluded_resolved = {path.resolve() for path in excluded or set()}
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() in excluded_resolved:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def renderer_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    version = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0 or not version:
        raise RuntimeError(f"无法读取 renderer 版本：{executable}")
    return version


def copy_submission_sources(
    *, template_dir: Path, source_dir: Path, stage_dir: Path, protected_files: set[str]
) -> None:
    shutil.copytree(template_dir, stage_dir, dirs_exist_ok=True)
    for source in sorted(item for item in source_dir.rglob("*") if item.is_file()):
        relative = source.relative_to(source_dir).as_posix()
        if relative in protected_files:
            raise ValueError(f"论文源稿不得覆盖批准模板受保护文件：{relative}")
        target = stage_dir / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def render_submission(
    *,
    profile_path: Path,
    template_dir: Path,
    source_dir: Path,
    source_entry: Path,
    output_pdf: Path,
    attestation_path: Path,
    renderer_id: str = "typst",
    renderer_executable: str | None = None,
) -> dict[str, Any]:
    profile = load_json_object(profile_path, "paper profile")
    template = load_json_object(template_dir / "template.json", "template manifest")
    profile_id = str(profile.get("profile_id", ""))
    template_id = str(template.get("template_id", ""))
    executable = renderer_executable or renderer_id
    version = renderer_version(executable)

    binding = check_profile_binding(
        paper_kind="submission_paper",
        profile_path=profile_path,
        declared_profile_id=profile_id,
        renderer_id=renderer_id,
        renderer_version=version,
        template_id=template_id,
        template_dir=template_dir,
    )
    if not binding["passed"]:
        messages = "；".join(str(issue["message"]) for issue in binding["issues"])
        raise ValueError(f"submission profile binding 失败：{messages}")

    entry = (source_dir / source_entry).resolve()
    try:
        entry.relative_to(source_dir.resolve())
    except ValueError as exc:
        raise ValueError("source_entry 必须位于 source_dir 内") from exc
    if not entry.is_file():
        raise FileNotFoundError(f"论文入口不存在：{entry}")
    if renderer_id != "typst":
        raise ValueError(f"当前未实现 renderer adapter：{renderer_id}")

    artifact_dir = attestation_path.parent
    source_manifest_path = artifact_dir / "paper_source_manifest.json"
    profile_snapshot_path = artifact_dir / "paper_profile.snapshot.json"
    template_manifest_path = artifact_dir / "paper_template_manifest.json"

    source_manifest = {
        "manifest_version": "1.0.0",
        "entry": source_entry.as_posix(),
        "files": build_file_manifest(source_dir, excluded={output_pdf, attestation_path}),
    }
    template_manifest = {
        "manifest_version": "1.0.0",
        "template_id": template_id,
        "renderer_id": renderer_id,
        "files": build_file_manifest(template_dir),
    }
    write_json(source_manifest_path, source_manifest)
    write_json(profile_snapshot_path, profile)
    write_json(template_manifest_path, template_manifest)

    protected_files = {
        str(item).replace("\\", "/")
        for item in template.get("protected_files", [])
        if isinstance(item, str)
    }
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paper-render-") as temporary:
        stage_dir = Path(temporary) / "paper"
        copy_submission_sources(
            template_dir=template_dir,
            source_dir=source_dir,
            stage_dir=stage_dir,
            protected_files=protected_files,
        )
        staged_entry = stage_dir / source_entry
        completed = subprocess.run(
            [executable, "compile", "--root", str(stage_dir), str(staged_entry), str(output_pdf)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"submission 编译失败：{completed.stderr.strip()}")
    if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
        raise RuntimeError("renderer 返回成功，但 submission PDF 不存在或为空")

    attestation = {
        "schema_version": "1.0.0",
        "paper_kind": "submission_paper",
        "profile_id": profile_id,
        "template_id": template_id,
        "renderer_id": renderer_id,
        "renderer_version": version,
        "source_manifest": source_manifest_path.name,
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "profile_snapshot": profile_snapshot_path.name,
        "profile_snapshot_sha256": sha256_file(profile_snapshot_path),
        "template_manifest": template_manifest_path.name,
        "template_manifest_sha256": sha256_file(template_manifest_path),
        "output_pdf": Path(os.path.relpath(output_pdf, artifact_dir)).as_posix(),
        "output_pdf_sha256": sha256_file(output_pdf),
        "compiled": True,
    }
    schema = load_json_object(
        ROOT / "schemas" / "paper_render_attestation.schema.json",
        "paper render attestation schema",
    )
    Draft202012Validator(schema).validate(attestation)
    write_json(attestation_path, attestation)
    return attestation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 Profile 批准的模板和 renderer 生成提交论文")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-entry", type=Path, default=Path("main.typ"))
    parser.add_argument("--renderer-id", default="typst")
    parser.add_argument("--renderer-executable")
    parser.add_argument("--output-pdf", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    attestation = render_submission(
        profile_path=args.profile,
        template_dir=args.template_dir,
        source_dir=args.source_dir,
        source_entry=args.source_entry,
        output_pdf=args.output_pdf,
        attestation_path=args.attestation,
        renderer_id=args.renderer_id,
        renderer_executable=args.renderer_executable,
    )
    print(json.dumps({"compiled": True, "output_pdf_sha256": attestation["output_pdf_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
