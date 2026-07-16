from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENDOR_ROOT = ROOT / ".vendor" / "mathmodelagent"
DEFAULT_MANIFEST_PATH = ROOT / "runtime_contracts" / "template_source_manifest_v1.json"
DEFAULT_OVERLAY_PATH = ROOT / "runtime_contracts" / "template_overlay_v1.json"
UPSTREAM_FILE_MANIFEST = ROOT / "upstream" / "mathmodelagent.sha256.json"
UPSTREAM_LOCK = ROOT / "UPSTREAM.lock.json"
TEMPLATE_ROOT = "skills/5writing/templates"
ENGINE_SUFFIX = {"typst": "", "xelatex": "-latex"}
ENGINE_ENTRY = {"typst": "main.typ", "xelatex": "main.tex"}

ALIASES: dict[str, list[str]] = {
    "en/apmcm": ["apmcm-en", "apmcm-english"],
    "en/default": ["default-en", "english-default"],
    "en/mcm": ["mcm", "icm", "comap"],
    "zh/apmcm": ["apmcm-zh", "亚太杯中文"],
    "zh/changsanjiao": ["changsanjiao", "长三角"],
    "zh/cumcm": ["cumcm", "全国赛", "国赛"],
    "zh/default": ["default-zh", "中文默认"],
    "zh/diangongbei": ["diangongbei", "电工杯"],
    "zh/dongsansheng": ["dongsansheng", "东三省"],
    "zh/huashubei": ["huashubei", "华数杯"],
    "zh/huaweibei": ["huaweibei", "华为杯"],
    "zh/huazhongbei": ["huazhongbei", "华中杯"],
    "zh/mathorcup": ["mathorcup", "mathor-cup"],
    "zh/mcm": ["mcm-zh", "mcm中文"],
    "zh/shuweibei": ["shuweibei", "数维杯"],
    "zh/stats": ["stats", "统计建模"],
    "zh/wuyibei": ["wuyibei", "五一杯"],
}


class TemplateRegistryError(ValueError):
    """模板注册、选择或来源校验失败。"""


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} 不存在：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TemplateRegistryError(f"{label} 必须是 JSON 对象：{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_tree_sha256(files: Iterable[dict[str, Any]]) -> str:
    canonical = json.dumps(
        list(files),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _provenance_index() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    provenance = load_json_object(UPSTREAM_FILE_MANIFEST, "上游文件哈希清单")
    lock = load_json_object(UPSTREAM_LOCK, "上游锁")
    records = provenance.get("files")
    if not isinstance(records, list):
        raise TemplateRegistryError("上游文件哈希清单 files 必须是数组")
    index = {
        str(record["path"]): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    }
    return index, lock


def _source_records(
    source_dir: str,
    *,
    vendor_root: Path,
    provenance_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    source_path = vendor_root / Path(source_dir)
    if not source_path.is_dir():
        raise TemplateRegistryError(f"模板来源目录不存在：{source_dir}")
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in source_path.rglob("*") if item.is_file()):
        source_relative = path.relative_to(vendor_root).as_posix()
        template_relative = path.relative_to(source_path).as_posix()
        provenance = provenance_index.get(source_relative)
        if provenance is None:
            raise TemplateRegistryError(f"模板文件不在固定上游哈希清单中：{source_relative}")
        actual_sha = sha256_file(path)
        actual_size = path.stat().st_size
        if provenance.get("sha256") != actual_sha or provenance.get("size") != actual_size:
            raise TemplateRegistryError(f"模板来源文件与固定上游哈希不一致：{source_relative}")
        records.append(
            {
                "path": template_relative,
                "sha256": actual_sha,
                "size_bytes": actual_size,
            }
        )
    return records


def generate_manifest(vendor_root: Path = DEFAULT_VENDOR_ROOT) -> dict[str, Any]:
    """从已校验的只读 Source Asset 生成确定性的模板注册表。"""
    provenance_index, lock = _provenance_index()
    template_root = vendor_root / Path(TEMPLATE_ROOT)
    if not template_root.is_dir():
        raise TemplateRegistryError("本地 Source Asset 缺少 5writing/templates")

    templates: list[dict[str, Any]] = []
    grouped: dict[str, dict[str, str]] = {}
    for language_dir in sorted(item for item in template_root.iterdir() if item.is_dir()):
        language = language_dir.name
        if language not in {"zh", "en"}:
            raise TemplateRegistryError(f"未知模板语言目录：{language}")
        for directory in sorted(item for item in language_dir.iterdir() if item.is_dir()):
            engine = "xelatex" if directory.name.endswith("-latex") else "typst"
            family = directory.name.removesuffix("-latex")
            logical_key = f"{language}/{family}"
            entry = ENGINE_ENTRY[engine]
            source_dir = directory.relative_to(vendor_root).as_posix()
            files = _source_records(
                source_dir,
                vendor_root=vendor_root,
                provenance_index=provenance_index,
            )
            if entry not in {record["path"] for record in files}:
                raise TemplateRegistryError(f"模板入口缺失：{source_dir}/{entry}")
            template_id = f"mma_{language}_{family.replace('-', '_')}_{engine}_v1"
            grouped.setdefault(logical_key, {})[engine] = template_id
            templates.append(
                {
                    "template_id": template_id,
                    "logical_key": logical_key,
                    "language": language,
                    "competition_family": family,
                    "engine": engine,
                    "renderer_id": engine,
                    "source_dir": source_dir,
                    "entry": entry,
                    "file_count": len(files),
                    "tree_sha256": canonical_tree_sha256(files),
                    "files": files,
                }
            )

    logical_keys: list[dict[str, Any]] = []
    for key, engines in sorted(grouped.items()):
        if set(engines) != {"typst", "xelatex"}:
            raise TemplateRegistryError(f"逻辑键必须同时提供 Typst 与 XeLaTeX：{key}")
        if key not in ALIASES:
            raise TemplateRegistryError(f"逻辑键缺少本仓别名定义：{key}")
        language, family = key.split("/", 1)
        logical_keys.append(
            {
                "key": key,
                "language": language,
                "competition_family": family,
                "aliases": ALIASES[key],
                "default_engine": "typst",
                "fallback_engine": "xelatex",
                "upstream_default_engine": "xelatex",
                "upstream_default_overridden": True,
                "templates": {
                    "typst": engines["typst"],
                    "xelatex": engines["xelatex"],
                },
            }
        )

    manifest = {
        "schema_version": "template_source_manifest_v1",
        "source": {
            "repository": lock["repository"]["url"],
            "commit": lock["repository"]["commit"],
            "license_path": lock["repository"]["license_path"],
            "template_root": TEMPLATE_ROOT,
        },
        "tree_hash_algorithm": "sha256-canonical-json-v1",
        "logical_keys": logical_keys,
        "templates": sorted(templates, key=lambda item: str(item["template_id"])),
    }
    validate_registry(manifest, verify_source=True, vendor_root=vendor_root)
    return manifest


def validate_registry(
    manifest: dict[str, Any],
    *,
    verify_source: bool = False,
    vendor_root: Path = DEFAULT_VENDOR_ROOT,
) -> None:
    schema = load_json_object(
        ROOT / "schemas" / "template_source_manifest.schema.json",
        "模板来源清单 Schema",
    )
    Draft202012Validator(schema).validate(manifest)
    overlay = load_json_object(DEFAULT_OVERLAY_PATH, "模板覆盖层")
    overlay_schema = load_json_object(
        ROOT / "schemas" / "template_overlay.schema.json",
        "模板覆盖层 Schema",
    )
    Draft202012Validator(overlay_schema).validate(overlay)

    provenance_index, lock = _provenance_index()
    source = manifest["source"]
    if source["repository"] != lock["repository"]["url"]:
        raise TemplateRegistryError("模板注册表 repository 与上游锁不一致")
    if source["commit"] != lock["repository"]["commit"]:
        raise TemplateRegistryError("模板注册表 commit 与上游锁不一致")
    if source["license_path"] != lock["repository"]["license_path"]:
        raise TemplateRegistryError("模板注册表 license_path 与上游锁不一致")

    keys = manifest["logical_keys"]
    templates = manifest["templates"]
    key_ids = [str(item["key"]) for item in keys]
    template_ids = [str(item["template_id"]) for item in templates]
    if len(key_ids) != len(set(key_ids)):
        raise TemplateRegistryError("模板逻辑键重复")
    if len(template_ids) != len(set(template_ids)):
        raise TemplateRegistryError("template_id 重复")
    known_templates = set(template_ids)
    for item in keys:
        if set(item["templates"].values()) - known_templates:
            raise TemplateRegistryError(f"逻辑键引用未知模板：{item['key']}")
    for template in templates:
        files = template["files"]
        paths = [str(item["path"]) for item in files]
        if len(paths) != len(set(paths)):
            raise TemplateRegistryError(f"模板文件路径重复：{template['template_id']}")
        if template["file_count"] != len(files):
            raise TemplateRegistryError(f"模板 file_count 不一致：{template['template_id']}")
        if template["tree_sha256"] != canonical_tree_sha256(files):
            raise TemplateRegistryError(f"模板 tree_sha256 不一致：{template['template_id']}")
        if template["entry"] not in paths:
            raise TemplateRegistryError(f"模板入口不在文件闭包中：{template['template_id']}")
        source_dir_text = str(template["source_dir"])
        source_prefix = f"{source_dir_text}/"
        provenance_records = {
            path.removeprefix(source_prefix): record
            for path, record in provenance_index.items()
            if path.startswith(source_prefix)
        }
        if set(provenance_records) != set(paths):
            raise TemplateRegistryError(f"模板注册表与上游哈希清单路径闭包不一致：{template['template_id']}")
        for record in files:
            provenance = provenance_records[str(record["path"])]
            if (
                provenance.get("sha256") != record["sha256"]
                or provenance.get("size") != record["size_bytes"]
            ):
                raise TemplateRegistryError(
                    f"模板注册表与上游哈希清单内容不一致：{template['template_id']}/{record['path']}"
                )
        if verify_source:
            source_dir = vendor_root / Path(source_dir_text)
            actual_paths = {
                path.relative_to(source_dir).as_posix()
                for path in source_dir.rglob("*")
                if path.is_file()
            }
            if actual_paths != set(paths):
                raise TemplateRegistryError(f"模板来源路径闭包漂移：{template['template_id']}")
            for record in files:
                path = source_dir / Path(str(record["path"]))
                if path.stat().st_size != record["size_bytes"] or sha256_file(path) != record["sha256"]:
                    raise TemplateRegistryError(f"模板来源哈希漂移：{template['template_id']}/{record['path']}")


def select_template(
    manifest: dict[str, Any],
    *,
    language: str,
    competition_family: str,
    runtime_profile_template: str | None = None,
    run_template: str | None = None,
    upstream_default_template: str | None = None,
    requested_engine: str | None = None,
) -> dict[str, Any]:
    """按 Runtime Profile > 当前 Run > 赛事默认 > 上游默认选择模板。"""
    key_index = {str(item["key"]): item for item in manifest["logical_keys"]}
    competition_default = f"{language}/{competition_family}"
    upstream_default = upstream_default_template or f"{language}/default"
    candidates = (
        ("runtime_profile", runtime_profile_template),
        ("current_run", run_template),
        ("competition_default", competition_default),
        ("upstream_default", upstream_default),
    )
    selected_source = ""
    selected_key = ""
    for source, key in candidates:
        if key is None:
            continue
        if key not in key_index:
            if source in {"runtime_profile", "current_run"}:
                raise TemplateRegistryError(f"{source} 指定未知模板逻辑键：{key}")
            continue
        selected_source = source
        selected_key = key
        break
    if not selected_key:
        raise TemplateRegistryError("没有可用的模板逻辑键")

    key_record = key_index[selected_key]
    engine = requested_engine or str(key_record["default_engine"])
    if engine not in {"typst", "xelatex"}:
        raise TemplateRegistryError(f"未知论文引擎：{engine}")
    template_id = key_record["templates"].get(engine)
    fallback_used = False
    if template_id is None:
        engine = str(key_record["fallback_engine"])
        template_id = key_record["templates"].get(engine)
        fallback_used = True
    if template_id is None:
        raise TemplateRegistryError(f"模板逻辑键没有可用引擎：{selected_key}")
    template_index = {str(item["template_id"]): item for item in manifest["templates"]}
    template = template_index[str(template_id)]
    return {
        "schema_version": "template_selection_v1",
        "logical_key": selected_key,
        "selection_source": selected_source,
        "template_id": template_id,
        "engine": engine,
        "renderer_id": template["renderer_id"],
        "entry": template["entry"],
        "source_dir": template["source_dir"],
        "source_tree_sha256": template["tree_sha256"],
        "fallback_used": fallback_used,
        "overlay_id": "windows_template_overlay_v1",
        "upstream_default_overridden": (
            engine != key_record["upstream_default_engine"]
            or selected_source != "upstream_default"
        ),
    }


def materialize_template(
    manifest: dict[str, Any],
    selection: dict[str, Any],
    *,
    target_dir: Path,
    vendor_root: Path = DEFAULT_VENDOR_ROOT,
) -> None:
    """校验来源后复制所选模板；不修改只读 Source Asset。"""
    validate_registry(manifest, verify_source=True, vendor_root=vendor_root)
    if target_dir.exists() and any(target_dir.iterdir()):
        raise TemplateRegistryError(f"模板目标目录必须为空：{target_dir}")
    template_index = {str(item["template_id"]): item for item in manifest["templates"]}
    template = template_index.get(str(selection.get("template_id")))
    if template is None:
        raise TemplateRegistryError("模板选择引用未知 template_id")
    source_dir = vendor_root / Path(str(template["source_dir"]))
    target_dir.mkdir(parents=True, exist_ok=True)
    for record in template["files"]:
        relative = Path(str(record["path"]))
        source = source_dir / relative
        target = target_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成、校验和选择 MathModelAgent 模板注册表")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="从只读 Source Asset 生成注册表")
    generate.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR_ROOT)
    generate.add_argument("--output", type=Path, default=DEFAULT_MANIFEST_PATH)
    validate = subparsers.add_parser("validate", help="校验已提交注册表")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    validate.add_argument("--verify-source", action="store_true")
    validate.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR_ROOT)
    select = subparsers.add_parser("select", help="按本仓优先级选择模板")
    select.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    select.add_argument("--language", required=True, choices=("zh", "en"))
    select.add_argument("--competition-family", required=True)
    select.add_argument("--runtime-profile-template")
    select.add_argument("--run-template")
    select.add_argument("--upstream-default-template")
    select.add_argument("--engine", choices=("typst", "xelatex"))
    select.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "generate":
        manifest = generate_manifest(args.vendor_root)
        write_json(args.output, manifest)
        print(json.dumps({"logical_keys": 17, "templates": 34}, ensure_ascii=False))
        return 0
    manifest = load_json_object(args.manifest, "模板来源清单")
    if args.command == "validate":
        validate_registry(
            manifest,
            verify_source=args.verify_source,
            vendor_root=args.vendor_root,
        )
        print(json.dumps({"valid": True}, ensure_ascii=False))
        return 0
    selection = select_template(
        manifest,
        language=args.language,
        competition_family=args.competition_family,
        runtime_profile_template=args.runtime_profile_template,
        run_template=args.run_template,
        upstream_default_template=args.upstream_default_template,
        requested_engine=args.engine,
    )
    if args.output:
        write_json(args.output, selection)
    print(json.dumps(selection, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
