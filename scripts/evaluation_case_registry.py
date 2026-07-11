"""晋级自动评估用例注册表的单一事实源。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tests" / "prompt_regression" / "evaluation_case_registry.json"
REGISTRY_SCHEMA_PATH = ROOT / "schemas" / "evaluation_case_registry.schema.json"
EVALUATOR_VERSION = "1.2.0"


def sha256_bytes(content: bytes) -> str:
    """计算原始字节的 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def validate_case_bytes(case_path: Path) -> bytes:
    """读取授权 YAML 的原始字节，并拒绝 CRLF 或孤立 CR 换行。"""
    raw = case_path.read_bytes()
    if b"\r\n" in raw or b"\r" in raw:
        raise ValueError(
            f"{case_path} 不是 LF 文件；请先执行换行规范化，禁止生成 CRLF 哈希"
        )
    return raw


def compute_case_sha256(case_path: Path) -> str:
    """计算经过 LF 校验的授权 YAML 原始字节哈希。"""
    return sha256_bytes(validate_case_bytes(case_path))


def substantive_assertion_count(case: Mapping[str, Any]) -> int:
    """统计真正会约束模型响应的断言，空容器不计入。"""
    expected = case.get("expected")
    if not isinstance(expected, Mapping):
        return 0

    count = 0
    values = expected.get("values")
    if isinstance(values, Mapping):
        count += sum(1 for key in values if isinstance(key, str) and key)

    required_paths = expected.get("must_have_paths")
    if isinstance(required_paths, list):
        count += sum(1 for item in required_paths if isinstance(item, str) and item)

    forbidden_values = expected.get("forbidden_values")
    if isinstance(forbidden_values, Mapping):
        for path, values_for_path in forbidden_values.items():
            if isinstance(path, str) and path and isinstance(values_for_path, list):
                count += sum(
                    1 for item in values_for_path if isinstance(item, str) and item
                )

    patch_not_applicable = expected.get("patch_not_applicable")
    if isinstance(patch_not_applicable, Mapping):
        count += sum(
            1 for patch_id in patch_not_applicable if isinstance(patch_id, str) and patch_id
        )

    if expected.get("requires_manual_confirmation") is True:
        count += 1

    must_not_contain = expected.get("must_not_contain")
    if isinstance(must_not_contain, list):
        count += sum(1 for item in must_not_contain if isinstance(item, str) and item)
    return count


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """读取注册表 JSON。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evaluation_case_registry 必须是 JSON 对象")
    return value


def _resolve_case_path(root: Path, raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("case_file 必须是非空相对路径")
    root = root.resolve()
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"case_file 位于仓库外：{raw_path}")
    if not path.is_file():
        raise ValueError(f"授权评测用例不存在：{raw_path}")
    return path


def _load_exact_case(case_path: Path, case_id: Any) -> Mapping[str, Any]:
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id 必须是非空字符串")
    data = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, Mapping) else None
    matches = [
        item
        for item in cases or []
        if isinstance(item, Mapping) and item.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise ValueError(f"case_id {case_id!r} 必须在 YAML 中恰好出现一次")
    return matches[0]


def build_expected_registry(
    registry: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    """仅派生 case_sha256，绝不覆盖人工授权字段。"""
    expected = json.loads(json.dumps(registry, ensure_ascii=False))
    cases = expected.get("cases")
    if not isinstance(cases, list):
        raise ValueError("evaluation_case_registry.cases 必须是数组")
    for item in cases:
        if not isinstance(item, dict):
            raise ValueError("evaluation_case_registry.cases 条目必须是对象")
        case_path = _resolve_case_path(root, item.get("case_file"))
        item["case_sha256"] = compute_case_sha256(case_path)
    return expected


def compare_registry(
    registry: Mapping[str, Any], *, root: Path = ROOT
) -> list[str]:
    """比较已记录和应派生的哈希，返回可直接展示的漂移信息。"""
    expected = build_expected_registry(registry, root=root)
    recorded_cases = registry.get("cases", [])
    expected_cases = expected.get("cases", [])
    issues: list[str] = []
    for recorded, derived in zip(recorded_cases, expected_cases, strict=True):
        if not isinstance(recorded, Mapping) or not isinstance(derived, Mapping):
            continue
        if recorded.get("case_sha256") != derived.get("case_sha256"):
            issues.append(
                "evaluation registry drift:\n"
                f"{recorded.get('case_id')}\n"
                f"recorded: {recorded.get('case_sha256')}\n"
                f"actual:   {derived.get('case_sha256')}\n\n"
                "Run:\npython scripts/update_evaluation_case_registry.py"
            )
    return issues


def validate_registry(registry: Mapping[str, Any], *, root: Path = ROOT) -> list[str]:
    """执行 Schema、字节、哈希、授权身份和断言强度的完整只读校验。"""
    issues: list[str] = []
    schema = json.loads(REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
    for error in sorted(
        Draft202012Validator(schema).iter_errors(registry),
        key=lambda item: list(item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        issues.append(f"evaluation registry Schema {location}: {error.message}")
    if issues:
        return issues
    if registry.get("evaluator_version") != EVALUATOR_VERSION:
        issues.append("evaluation registry evaluator_version 与当前评估器不一致")

    cases = registry.get("cases", [])
    seen: set[tuple[Any, Any]] = set()
    for item in cases:
        if not isinstance(item, Mapping):
            continue
        identity = (item.get("case_id"), item.get("case_file"))
        if identity in seen:
            issues.append(f"evaluation registry 存在重复授权身份：{identity}")
            continue
        seen.add(identity)
        try:
            case_path = _resolve_case_path(root, item.get("case_file"))
            case = _load_exact_case(case_path, item.get("case_id"))
            compute_case_sha256(case_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            issues.append(str(exc))
            continue
        minimum = item.get("minimum_assertion_count")
        assertions = substantive_assertion_count(case)
        if not isinstance(minimum, int) or assertions < minimum:
            issues.append(
                "evaluation registry 实质断言不足："
                f"{item.get('case_id')} 当前 {assertions}，授权下限 {minimum}"
            )
        target_patch = item.get("target_patch")
        expected = case.get("expected", {})
        asserted_patches = (
            set(expected.get("patch_not_applicable", {}))
            if isinstance(expected, Mapping)
            and isinstance(expected.get("patch_not_applicable"), Mapping)
            else set()
        )
        if target_patch is not None and target_patch not in asserted_patches:
            issues.append(
                "evaluation registry target_patch 未被用例断言覆盖："
                f"{item.get('case_id')} / {target_patch}"
            )
    try:
        issues.extend(compare_registry(registry, root=root))
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
    return issues


def find_authorized_case(
    registry: Mapping[str, Any],
    *,
    case_id: Any,
    case_file: Any,
    case_sha256: Any,
) -> Mapping[str, Any] | None:
    """按 ID、路径和内容哈希精确匹配一条授权用例。"""
    cases = registry.get("cases")
    if not isinstance(cases, list):
        return None
    matches = [
        item
        for item in cases
        if isinstance(item, Mapping)
        and item.get("case_id") == case_id
        and item.get("case_file") == case_file
        and item.get("case_sha256") == case_sha256
    ]
    return matches[0] if len(matches) == 1 else None
