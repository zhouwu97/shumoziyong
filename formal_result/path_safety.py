"""执行合同路径的跨平台安全校验。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def validate_contract_relative_path(value: str, allowed_root: str, label: str) -> None:
    """验证合同路径严格位于指定的首段目录，且在 Windows/POSIX 上含义一致。"""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} 必须是非空相对路径")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise ValueError(f"{label} 必须是安全的 POSIX 相对路径")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} 禁止空段、. 或 ..：{value}")
    if parts[0] != allowed_root:
        raise ValueError(f"{label} 必须位于 {allowed_root}/ 下：{value}")
    for part in parts:
        # Windows 会忽略设备名后的扩展名，并折叠段末的空格或句点。
        normalized = part.rstrip(" .")
        device_name = normalized.split(".", 1)[0].upper()
        if not normalized or device_name in WINDOWS_RESERVED_NAMES:
            raise ValueError(f"{label} 包含 Windows 保留名称：{value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.parts != tuple(parts):
        raise ValueError(f"{label} 不是规范的 POSIX 相对路径：{value}")


def validate_execution_spec_paths(spec: Mapping[str, Any]) -> None:
    """验证 Execution Spec 中所有具有路径语义的字段。"""
    workspace = spec.get("declared_workspace")
    if not isinstance(workspace, str):
        raise ValueError("declared_workspace 必须是字符串")
    workspace_root = workspace.split("/", 1)[0]
    if workspace_root not in {"workspace", "collector_workspace"}:
        raise ValueError("declared_workspace 根目录非法")
    validate_contract_relative_path(workspace, workspace_root, "declared_workspace")

    for index, value in enumerate(spec.get("declared_writable_paths", [])):
        validate_contract_relative_path(value, workspace_root, f"declared_writable_paths[{index}]")

    for task_index, task in enumerate(spec.get("tasks", [])):
        prefix = f"tasks[{task_index}]"
        validate_contract_relative_path(task["entrypoint"], "code", f"{prefix}.entrypoint")
        validate_contract_relative_path(
            task["working_directory"], workspace_root, f"{prefix}.working_directory"
        )
        for input_index, item in enumerate(task["inputs"]):
            input_path = item["path"]
            input_root = input_path.split("/", 1)[0]
            if input_root not in {"problem", workspace_root}:
                raise ValueError(f"{prefix}.inputs[{input_index}].path 根目录非法")
            validate_contract_relative_path(
                input_path, input_root, f"{prefix}.inputs[{input_index}].path"
            )
        for output_index, item in enumerate(task["required_outputs"]):
            validate_contract_relative_path(
                item["path"], workspace_root, f"{prefix}.required_outputs[{output_index}].path"
            )
            schema_path = item.get("schema_path")
            if schema_path is not None:
                validate_contract_relative_path(
                    schema_path, "schemas", f"{prefix}.required_outputs[{output_index}].schema_path"
                )
        for check_index, check in enumerate(task["acceptance_checks"]):
            if check["kind"] == "file_exists":
                expectation = check["expectation"]
                # 验收路径相对于 Workspace，合同中不得再次带 Workspace 前缀。
                validate_contract_relative_path(
                    f"{workspace_root}/{expectation}",
                    workspace_root,
                    f"{prefix}.acceptance_checks[{check_index}].expectation",
                )
