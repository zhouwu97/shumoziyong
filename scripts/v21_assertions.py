"""v2.1 公开/封存断言注册器。

断言函数必须显式登记；Executor 不接收表达式字符串，也不执行 eval/exec。
封存断言只在独立评审环境解析，不能从 Runtime Pack 读取。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping


Assertion = Callable[[Mapping[str, Any]], bool]
_REGISTRY: dict[str, Assertion] = {}


def register_assertion(assertion_id: str) -> Callable[[Assertion], Assertion]:
    def decorator(function: Assertion) -> Assertion:
        if not assertion_id or assertion_id in _REGISTRY:
            raise ValueError(f"断言 ID 重复或为空：{assertion_id!r}")
        _REGISTRY[assertion_id] = function
        return function

    return decorator


@register_assertion("public.unit_declared")
def unit_declared(payload: Mapping[str, Any]) -> bool:
    """公开合同：变量必须声明单位，或明确声明无量纲。"""
    variables = payload.get("variables", [])
    return bool(variables) and all(
        isinstance(item, Mapping) and isinstance(item.get("unit"), str) and bool(item["unit"].strip())
        for item in variables
    )


@register_assertion("public.boundary_case_declared")
def boundary_case_declared(payload: Mapping[str, Any]) -> bool:
    cases = payload.get("limit_cases", [])
    return bool(cases) and all(isinstance(item, Mapping) and item.get("case_id") for item in cases)


def registered_assertions() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def evaluate_registered(assertion_id: str, payload: Mapping[str, Any]) -> bool:
    try:
        function = _REGISTRY[assertion_id]
    except KeyError as exc:
        raise ValueError(f"未登记的断言函数：{assertion_id}") from exc
    return bool(function(payload))


def validate_assertion_refs(
    refs: list[Mapping[str, Any]],
    *,
    runtime_pack_text: str = "",
    runtime_manifest: Mapping[str, Any] | None = None,
) -> list[str]:
    """检查断言引用完整性，并阻止封存断言进入 Executor Runtime Pack。"""
    errors: list[str] = []
    listed_files: set[str] = set()
    for section in (runtime_manifest or {}).values():
        if isinstance(section, Mapping) and "path" in section:
            listed_files.add(str(section["path"]))
        elif isinstance(section, list):
            listed_files.update(str(item.get("path")) for item in section if isinstance(item, Mapping) and item.get("path"))
    for ref in refs:
        assertion_id = str(ref.get("assertion_set_id", ""))
        path = str(ref.get("path", ""))
        if ref.get("layer") == "sealed":
            if ref.get("sealed") is not True or ref.get("blind_evidence") is not True:
                errors.append(f"封存断言 {assertion_id} 未满足 sealed=true 且 blind_evidence=true")
            if path in listed_files or path in runtime_pack_text or str(ref.get("sha256", "")) in runtime_pack_text:
                errors.append(f"封存断言 {assertion_id} 已进入 Executor Runtime Pack")
        if ref.get("layer") == "public" and ref.get("sealed") is True:
            errors.append(f"公开断言 {assertion_id} 不能标记 sealed=true")
    return errors


def assertion_file_ref(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    return {"path": path.as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def load_public_assertions(path: Path) -> list[dict[str, Any]]:
    """只加载结构化公开断言；不接受可执行表达式字段。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("公开断言文件必须是数组")
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("assertion_id"), str):
            raise ValueError("公开断言必须包含已登记 assertion_id")
        if item["assertion_id"] not in _REGISTRY:
            raise ValueError(f"公开断言未登记：{item['assertion_id']}")
        if any(key in item for key in ("expression", "code", "eval", "exec")):
            raise ValueError("断言文件禁止包含动态表达式或代码")
    return value
