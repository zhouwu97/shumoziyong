from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - 仅在缺少依赖时触发
    raise SystemExit("缺少 jsonschema，请先执行：pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "material_manifest.schema.json"
CATEGORY_NAMES = ("problem", "attachments", "templates")


@dataclass
class CategoryVerification:
    """记录一个材料类别的验证结果，供运行目录和命令行复用。"""

    required: bool = False
    declared_files: int = 0
    verified_files: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "ready" if not self.errors else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "declared_files": self.declared_files,
            "verified_files": self.verified_files,
            "status": self.status,
            "errors": self.errors,
        }


@dataclass
class MaterialVerificationResult:
    """旧题材料校验的机器可读结果。"""

    material_root: Path
    manifest_path: Path
    problem_id: str | None = None
    manifest_sha256: str | None = None
    errors: list[str] = field(default_factory=list)
    categories: dict[str, CategoryVerification] = field(
        default_factory=lambda: {name: CategoryVerification() for name in CATEGORY_NAMES}
    )
    files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors and all(not category.errors for category in self.categories.values())

    @property
    def status(self) -> str:
        return "ready" if self.ready else "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "material_root": str(self.material_root),
            "material_manifest": str(self.manifest_path),
            "material_manifest_sha256": self.manifest_sha256,
            "status": self.status,
            "ready": self.ready,
            "errors": self.errors,
            "categories": {name: category.to_dict() for name, category in self.categories.items()},
            "files": self.files,
        }


def sha256_bytes(content: bytes) -> str:
    """计算字节内容的 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def _load_json(path: Path) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
    """读取 JSON 清单，并将格式问题转换为明确错误信息。"""
    try:
        content = path.read_bytes()
    except OSError as exc:
        return None, None, f"无法读取材料清单：{path}（{exc}）"
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, content, f"材料清单不是有效 UTF-8 JSON：{path}（{exc}）"
    if not isinstance(data, dict):
        return None, content, f"材料清单根节点必须为对象：{path}"
    return data, content, None


def _validate_schema(data: dict[str, Any]) -> list[str]:
    """返回 JSON Schema 校验错误，避免仅凭目录存在就认定材料可用。"""
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - 仓库损坏时触发
        return [f"无法读取材料清单 Schema：{SCHEMA_PATH}（{exc}）"]

    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    return [
        f"材料清单 Schema：{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
        for error in errors
    ]


def _resolve_declared_file(material_root: Path, raw_path: str) -> tuple[Path | None, str | None]:
    """安全解析清单路径，拒绝绝对路径与目录穿越。"""
    declared = Path(raw_path)
    if declared.is_absolute():
        return None, f"材料清单路径不得为绝对路径：{raw_path}"
    candidate = (material_root / declared).resolve()
    if not candidate.is_relative_to(material_root.resolve()):
        return None, f"材料清单路径逃逸材料根目录：{raw_path}"
    return candidate, None


def verify_materials(
    material_root: Path,
    *,
    manifest_path: Path | None = None,
    expected_problem_id: str | None = None,
) -> MaterialVerificationResult:
    """验证题面、附件、模板及所有已声明文件的 SHA-256。

    材料只有在清单存在、Schema 合法、必需类别完整、所有文件存在且哈希一致时才会返回 ready。
    """
    material_root = material_root.resolve()
    manifest_path = (manifest_path or material_root / "material_manifest.json").resolve()
    result = MaterialVerificationResult(material_root=material_root, manifest_path=manifest_path)

    if not material_root.is_dir():
        result.errors.append(f"材料根目录不存在或不是目录：{material_root}")
        return result
    if not manifest_path.is_file():
        result.errors.append(f"缺少机器可读材料清单：{manifest_path}")
        return result
    if not manifest_path.is_relative_to(material_root):
        result.errors.append(f"材料清单必须位于材料根目录内：{manifest_path}")
        return result

    data, content, load_error = _load_json(manifest_path)
    if content is not None:
        result.manifest_sha256 = sha256_bytes(content)
    if load_error:
        result.errors.append(load_error)
        return result
    assert data is not None

    result.errors.extend(_validate_schema(data))
    result.problem_id = data.get("problem_id") if isinstance(data.get("problem_id"), str) else None
    if expected_problem_id and result.problem_id != expected_problem_id:
        result.errors.append(
            f"材料清单题号不匹配：期望 {expected_problem_id}，实际 {result.problem_id or '<缺失>'}"
        )
    if data.get("contains_answer_or_solution") is True:
        result.errors.append("材料清单声明包含答案或题解，不能作为无泄漏旧题材料")

    categories = data.get("categories")
    if not isinstance(categories, dict):
        return result

    declared_paths: set[str] = set()
    for category_name in CATEGORY_NAMES:
        category_data = categories.get(category_name)
        category_result = result.categories[category_name]
        if not isinstance(category_data, dict):
            category_result.errors.append(f"材料类别缺失或格式错误：{category_name}")
            continue

        category_result.required = category_data.get("required") is True
        files = category_data.get("files")
        if not isinstance(files, list):
            category_result.errors.append(f"材料类别 files 必须为数组：{category_name}")
            continue
        category_result.declared_files = len(files)
        if category_result.required and not files:
            category_result.errors.append(f"必需材料类别为空：{category_name}")

        for item in files:
            if not isinstance(item, dict):
                category_result.errors.append(f"{category_name} 存在非对象文件条目")
                continue
            raw_path = item.get("path")
            expected_sha = item.get("sha256")
            if not isinstance(raw_path, str) or not isinstance(expected_sha, str):
                category_result.errors.append(f"{category_name} 文件条目缺少 path 或 sha256")
                continue
            if raw_path in declared_paths:
                category_result.errors.append(f"材料文件重复声明：{raw_path}")
                continue
            declared_paths.add(raw_path)

            resolved, path_error = _resolve_declared_file(material_root, raw_path)
            if path_error:
                category_result.errors.append(path_error)
                continue
            assert resolved is not None
            if not resolved.is_file():
                category_result.errors.append(f"材料文件不存在：{raw_path}")
                continue

            actual_content = resolved.read_bytes()
            actual_sha = sha256_bytes(actual_content)
            if actual_sha != expected_sha:
                category_result.errors.append(
                    f"材料文件 SHA-256 不匹配：{raw_path}（期望 {expected_sha}，实际 {actual_sha}）"
                )
                continue

            category_result.verified_files += 1
            result.files.append(
                {
                    "category": category_name,
                    "path": raw_path.replace("\\", "/"),
                    "size": len(actual_content),
                    "sha256": actual_sha,
                }
            )

    result.files.sort(key=lambda item: (item["category"], item["path"]))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验旧题材料清单、题面、附件、模板和 SHA-256。")
    parser.add_argument("--materials", required=True, help="材料根目录。")
    parser.add_argument("--manifest", help="材料清单路径；默认使用 <materials>/material_manifest.json。")
    parser.add_argument("--problem", help="期望题号；提供后必须与清单 problem_id 一致。")
    parser.add_argument("--output", help="将机器可读校验报告写入指定 JSON 文件。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    material_root = Path(args.materials)
    manifest_path = Path(args.manifest) if args.manifest else None
    report = verify_materials(
        material_root,
        manifest_path=manifest_path,
        expected_problem_id=args.problem,
    )
    rendered = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if report.ready else 2)


if __name__ == "__main__":
    main()
