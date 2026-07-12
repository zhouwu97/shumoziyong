"""Execution Spec 到物化 Sandbox 命令的唯一编译合同。"""

from __future__ import annotations

import hashlib
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .canonicalization import canonical_bytes
from .errors import FormalResultVerificationError


def _relative_suffix(path: str, root: str, label: str) -> str:
    if path == root:
        return "."
    prefix = root.rstrip("/") + "/"
    if not path.startswith(prefix):
        raise FormalResultVerificationError(f"{label} 越出 declared_workspace")
    return path.removeprefix(prefix)


def compile_execution_command(
    spec: Mapping[str, Any],
    materialized_root: Path,
    *,
    execution_id: str,
    challenge_nonce: str,
) -> dict[str, Any]:
    """编译单任务单 seed 合同，返回可由验证器稳定复算的逻辑命令。"""
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], Mapping):
        raise FormalResultVerificationError("M3A 只接受单任务 Execution Spec")
    task = tasks[0]
    seeds = task.get("seed_policy", {}).get("seeds")
    if not isinstance(seeds, list) or len(seeds) != 1 or not isinstance(seeds[0], int):
        raise FormalResultVerificationError("M3A 只接受单 seed Execution Spec")
    argv = task.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise FormalResultVerificationError("Execution Spec argv 非法")
    entrypoint_index = task.get("entrypoint_arg_index")
    if entrypoint_index != 1 or len(argv) <= entrypoint_index:
        raise FormalResultVerificationError("Execution Spec entrypoint 参数缺失")
    workspace = str(spec.get("declared_workspace"))
    working = str(task.get("working_directory"))
    cwd_relative = _relative_suffix(working, workspace, "working_directory")
    entry_arg = str(argv[entrypoint_index])
    if "\\" in entry_arg or ":" in entry_arg or entry_arg.startswith("/"):
        raise FormalResultVerificationError("entrypoint argv 必须是 POSIX 相对路径")
    resolved_entry = posixpath.normpath(
        posixpath.join("" if cwd_relative == "." else cwd_relative, entry_arg)
    )
    if resolved_entry.startswith("../") or resolved_entry != task.get("entrypoint"):
        raise FormalResultVerificationError("argv 未解析到批准的 entrypoint")
    cwd = materialized_root if cwd_relative == "." else materialized_root.joinpath(
        *PurePosixPath(cwd_relative).parts
    )
    try:
        cwd.resolve().relative_to(materialized_root.resolve())
    except ValueError as exc:
        raise FormalResultVerificationError("物化 working_directory 越界") from exc
    checks = task.get("acceptance_checks")
    if not isinstance(checks, list) or not checks:
        raise FormalResultVerificationError("Execution Spec 缺少 acceptance_checks")
    for check in checks:
        if not isinstance(check, Mapping) or check.get("kind") != "file_exists":
            raise FormalResultVerificationError("M3A 只支持 file_exists acceptance check")
        expectation = check.get("expectation")
        if not isinstance(expectation, str) or not expectation.startswith("output/"):
            raise FormalResultVerificationError("acceptance check 必须绑定 output/ 下文件")
    seed = seeds[0]
    environment_overrides = {
        "PYTHONHASHSEED": str(seed),
        "SHUMO_EXECUTION_SEED": str(seed),
        "SHUMO_EXECUTION_CHALLENGE": challenge_nonce,
        "SHUMO_RUN_ID": str(spec.get("run_id")),
        "SHUMO_EXECUTION_ID": execution_id,
    }
    return {
        "resolved_argv": list(argv),
        "resolved_working_directory": cwd_relative,
        "resolved_working_directory_path": str(cwd),
        "seed": seed,
        "environment_overrides": environment_overrides,
        "acceptance_checks": [dict(check) for check in checks],
    }


def launch_command_sha256(
    compiled: Mapping[str, Any],
    *,
    start_exe_sha256: str,
    python_sha256: str,
    sandboxie_box_name: str,
) -> str:
    stable = {
        "start_exe_sha256": start_exe_sha256,
        "python_sha256": python_sha256,
        "sandboxie_box_name": sandboxie_box_name,
        "resolved_argv": compiled["resolved_argv"],
        "resolved_working_directory": compiled["resolved_working_directory"],
        "seed": compiled["seed"],
        "environment_overrides": compiled["environment_overrides"],
    }
    return hashlib.sha256(canonical_bytes(stable)).hexdigest()


def sandbox_policy_sha256(settings: list[str]) -> str:
    return hashlib.sha256(canonical_bytes(settings)).hexdigest()
