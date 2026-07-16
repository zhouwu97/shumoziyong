"""校验 MathModelAgent 提取需求、来源哈希和 Native Adapter 映射闭包。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SOURCE_COMMIT = "be9c59c1aaa13c3dcb74452ea5cae11dada27589"
REGISTRY_FILES = (
    "production_requirements_v1.json",
    "paper_requirements_v1.json",
    "figure_requirements_v1.json",
    "verity_requirements_v1.json",
)
MAPPING_FILE = "upstream_requirement_mapping_v1.json"
PLUGIN_PATH = "prompt_plugins/plugin_competition_production_v1.md"
FORBIDDEN_UPSTREAM_RUNTIME_MARKERS = (
    ".vendor/",
    "1start-mathmodel",
    "allowed-tools:",
    "Bash(*)",
    "WebSearch",
)
EXPECTED_AUTHORITY = {
    "generate_results": False,
    "modify_paper": False,
    "decide_gate_pass": False,
    "advance_stage": False,
    "execute_upstream_content": False,
}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层不是对象：{path}")
    return value


def validate_requirement_bundle(root: Path) -> list[str]:
    """返回全部一致性问题；空数组表示需求与映射闭包有效。"""
    issues: list[str] = []
    requirements_dir = root / "runtime_contracts" / "upstream_requirements"
    manifest = _load_object(root / "upstream" / "mathmodelagent.sha256.json")
    manifest_files = {
        entry["path"]: entry["sha256"]
        for entry in manifest.get("files", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("path"), str)
        and isinstance(entry.get("sha256"), str)
    }

    requirements_by_id: dict[str, dict[str, Any]] = {}
    mapping_for_requirement: dict[str, str] = {}
    expected_prefix = {
        "production": "PROD-",
        "paper": "PAPER-",
        "figure": "FIG-",
        "verity": "VER-",
    }
    for filename in REGISTRY_FILES:
        registry = _load_object(requirements_dir / filename)
        if registry.get("source_commit") != SOURCE_COMMIT:
            issues.append(f"{filename}: source_commit 不匹配")
        domain = registry.get("domain")
        prefix = expected_prefix.get(str(domain), "")
        for requirement in registry.get("requirements", []):
            if not isinstance(requirement, dict):
                issues.append(f"{filename}: requirement 不是对象")
                continue
            requirement_id = requirement.get("requirement_id")
            if not isinstance(requirement_id, str):
                issues.append(f"{filename}: requirement_id 缺失")
                continue
            if requirement_id in requirements_by_id:
                issues.append(f"需求 ID 重复：{requirement_id}")
            if prefix and not requirement_id.startswith(prefix):
                issues.append(f"需求 ID 与 domain 不一致：{requirement_id}")
            requirements_by_id[requirement_id] = requirement
            mapping_id = requirement.get("mapping_id")
            if isinstance(mapping_id, str):
                mapping_for_requirement[requirement_id] = mapping_id
            for source_ref in requirement.get("source_refs", []):
                if not isinstance(source_ref, dict):
                    issues.append(f"{requirement_id}: source_ref 不是对象")
                    continue
                source_path = source_ref.get("path")
                source_hash = source_ref.get("sha256")
                if manifest_files.get(source_path) != source_hash:
                    issues.append(f"{requirement_id}: 来源哈希不匹配：{source_path}")

    mapping_registry = _load_object(requirements_dir / MAPPING_FILE)
    if mapping_registry.get("source_commit") != SOURCE_COMMIT:
        issues.append("映射注册表 source_commit 不匹配")
    if mapping_registry.get("adapter_authority") != EXPECTED_AUTHORITY:
        issues.append("Adapter 权限边界不匹配")

    mapped_ids: set[str] = set()
    seen_mapping_ids: set[str] = set()
    for mapping in mapping_registry.get("mappings", []):
        if not isinstance(mapping, dict):
            issues.append("mapping 不是对象")
            continue
        mapping_id = mapping.get("mapping_id")
        if not isinstance(mapping_id, str):
            issues.append("mapping_id 缺失")
            continue
        if mapping_id in seen_mapping_ids:
            issues.append(f"映射 ID 重复：{mapping_id}")
        seen_mapping_ids.add(mapping_id)
        for requirement_id in mapping.get("requirement_ids", []):
            if requirement_id in mapped_ids:
                issues.append(f"需求被重复映射：{requirement_id}")
            mapped_ids.add(requirement_id)
            if requirement_id not in requirements_by_id:
                issues.append(f"映射引用未知需求：{requirement_id}")
            elif mapping_for_requirement.get(requirement_id) != mapping_id:
                issues.append(f"需求 mapping_id 与映射合同不一致：{requirement_id}")
        for target_contract in mapping.get("target_contracts", []):
            if not isinstance(target_contract, str) or not (root / target_contract).is_file():
                issues.append(f"映射目标合同不存在：{target_contract}")

    expected_ids = set(requirements_by_id)
    if mapped_ids != expected_ids:
        missing = sorted(expected_ids - mapped_ids)
        extra = sorted(mapped_ids - expected_ids)
        if missing:
            issues.append(f"需求缺少映射：{', '.join(missing)}")
        if extra:
            issues.append(f"映射存在未知需求：{', '.join(extra)}")

    plugin_text = (root / PLUGIN_PATH).read_text(encoding="utf-8")
    for marker in FORBIDDEN_UPSTREAM_RUNTIME_MARKERS:
        if marker in plugin_text:
            issues.append(f"Adapter 包含禁止的上游运行时标记：{marker}")
    for required_text in (
        '"generate_results": false',
        '"modify_paper": false',
        '"decide_gate_pass": false',
        '"advance_stage": false',
    ):
        if required_text not in plugin_text:
            issues.append(f"Adapter 缺少固定权限声明：{required_text}")

    return issues
