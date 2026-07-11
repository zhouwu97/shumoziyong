"""晋级自动评估用例的授权注册表。

运行目录中的 automatic_evaluation.json 只是一次评估记录，不能自行声明
它使用的用例可信。该模块把用例 ID、路径、内容哈希和最低断言数绑定到
版本控制中的注册表，供写入端与验证端共用。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tests" / "prompt_regression" / "evaluation_case_registry.json"


def sha256_bytes(content: bytes) -> str:
    """计算文件内容的 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


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
    """读取注册表；结构化 Schema 校验由证据验证入口执行。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("evaluation_case_registry 必须是 JSON 对象")
    return value


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
