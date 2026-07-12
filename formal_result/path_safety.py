"""执行合同路径的跨平台安全校验。"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

CONTRACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_portable_segment(part: str, label: str, value: str) -> None:
    normalized = part.rstrip(" .")
    if normalized != part:
        raise ValueError(f"{label} 的路径段禁止尾随空格或句点：{value}")
    device_name = normalized.split(".", 1)[0].upper()
    if not normalized or device_name in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} 包含 Windows 保留名称：{value}")


def validate_contract_id(value: str, label: str) -> None:
    """验证会进入路径的合同 ID 在 Windows/POSIX 上均可安全使用。"""
    if not isinstance(value, str) or not CONTRACT_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} 必须是安全的单段合同 ID")
    _validate_portable_segment(value, label, value)


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
        _validate_portable_segment(part, label, value)
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


def validate_execution_command_bindings(spec: Mapping[str, Any], run_root: Path) -> None:
    """确认每个 Python argv 都从声明工作目录解析到批准入口。"""
    workspace = run_root.joinpath(
        *PurePosixPath(spec["declared_workspace"]).parts
    ).resolve()
    for task in spec["tasks"]:
        label = f"任务 {task['task_id']}"
        argv = task["argv"]
        runner_name = Path(argv[0]).name.casefold()
        if task.get("runner") != "python" or not re.fullmatch(
            r"python(?:3(?:\.\d+)?)?(?:\.exe)?", runner_name
        ):
            raise ValueError(f"{label} runner 不是受支持的 Python 解释器")
        index = task.get("entrypoint_arg_index")
        if index != 1 or len(argv) <= index:
            raise ValueError(f"{label} 缺少受绑定的 entrypoint 参数")
        entrypoint_arg = argv[index]
        if (
            not isinstance(entrypoint_arg, str)
            or not entrypoint_arg
            or entrypoint_arg.startswith("/")
            or "\\" in entrypoint_arg
            or ":" in entrypoint_arg
        ):
            raise ValueError(f"{label} entrypoint 参数必须是 POSIX 相对路径")
        working = run_root.joinpath(
            *PurePosixPath(task["working_directory"]).parts
        ).resolve()
        try:
            working.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"{label} working_directory 越出 declared_workspace") from exc
        command_entrypoint = working.joinpath(*PurePosixPath(entrypoint_arg).parts).resolve()
        approved_entrypoint = workspace.joinpath(
            *PurePosixPath(task["entrypoint"]).parts
        ).resolve()
        if command_entrypoint != approved_entrypoint:
            raise ValueError(f"{label} argv 未解析到批准的 entrypoint")
