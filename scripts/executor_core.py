"""最小 Executor Core：按已批准的 execution_spec 真实运行候选代码并封存原始记录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from process_tree import ProcessTreeTimeoutExpired, run_process_tree

from formal_result.path_safety import (
    validate_execution_command_bindings,
    validate_execution_spec_paths,
)
from formal_result.identity import IMMUTABLE_IDENTITY_FIELDS


ROOT = Path(__file__).resolve().parents[1]
SPEC_SCHEMA_PATH = ROOT / "schemas" / "execution_spec.schema.json"
RECORD_SCHEMA_PATH = ROOT / "schemas" / "execution_record.schema.json"
BLOCKER_SCHEMA_PATH = ROOT / "schemas" / "executor_blocker.schema.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return value


def _validate(value: Mapping[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_object(schema_path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"{label} 不符合 Schema：{details}")


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径越出 Run 目录：{candidate}") from exc
    return resolved


def _safe_spec_file(spec_path: Path, run_dir: Path) -> Path:
    """在解析链接前确认 Execution Spec 是 Run 内唯一的普通文件。"""
    absolute = spec_path.absolute()
    expected = run_dir / "execution_spec.json"
    if absolute != expected:
        raise ValueError(f"Executor 只允许读取 {expected}")
    if absolute.is_symlink():
        raise ValueError(f"Execution Spec 禁止符号链接：{spec_path}")
    if not absolute.is_file():
        raise ValueError(f"Execution Spec 不存在：{spec_path}")
    if os.stat(absolute, follow_symlinks=False).st_nlink != 1:
        raise ValueError(f"Execution Spec 禁止 hardlink：{spec_path}")
    resolved = absolute.resolve()
    if resolved != expected or resolved.parent != run_dir:
        raise ValueError(f"Execution Spec 解析后不在 Run Root：{spec_path}")
    return resolved


def _task_working_directory(task: Mapping[str, Any], workspace: Path, run_dir: Path) -> Path:
    working = _inside(run_dir, run_dir.joinpath(*PurePosixPath(task["working_directory"]).parts))
    try:
        working.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"任务 {task['task_id']} working_directory 越出 declared_workspace") from exc
    return working


def _resolve_approved_command(
    task: Mapping[str, Any], workspace: Path, cwd: Path
) -> Path:
    """确认 Python 命令实际解析到合同批准的唯一入口文件。"""
    argv = task["argv"]
    if task.get("runner") != "python" or argv[0] != "python":
        raise ValueError(f"任务 {task['task_id']} runner token 必须严格等于 python")
    entrypoint_index = task.get("entrypoint_arg_index")
    if entrypoint_index != 1 or len(argv) <= entrypoint_index:
        raise ValueError(f"任务 {task['task_id']} 缺少受绑定的 entrypoint 参数")
    entrypoint_arg = argv[entrypoint_index]
    if (
        not isinstance(entrypoint_arg, str)
        or not entrypoint_arg
        or entrypoint_arg.startswith("/")
        or "\\" in entrypoint_arg
        or ":" in entrypoint_arg
    ):
        raise ValueError(f"任务 {task['task_id']} entrypoint 参数必须是 POSIX 相对路径")
    command_entrypoint = _inside(
        workspace, cwd.joinpath(*PurePosixPath(entrypoint_arg).parts)
    )
    approved_entrypoint = _inside(
        workspace, workspace.joinpath(*PurePosixPath(task["entrypoint"]).parts)
    )
    if command_entrypoint != approved_entrypoint:
        raise ValueError(f"任务 {task['task_id']} argv 未解析到批准的 entrypoint")
    if not approved_entrypoint.is_file():
        raise ValueError(f"任务 {task['task_id']} 缺少批准的 entrypoint")
    return approved_entrypoint


def _file_ref(path: Path, run_dir: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.resolve().relative_to(run_dir.resolve()).as_posix(),
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _check_inputs(task: Mapping[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in task["inputs"]:
        path = _inside(run_dir, run_dir / item["path"])
        if not path.is_file():
            raise ValueError(f"任务 {task['task_id']} 缺少已声明输入：{item['path']}")
        reference = _file_ref(path, run_dir)
        if reference["sha256"] != item["sha256"]:
            raise ValueError(f"任务 {task['task_id']} 输入哈希不匹配：{item['path']}")
        refs.append(reference)
    return refs


def _check_acceptance(
    task: Mapping[str, Any], workspace: Path, run_dir: Path
) -> tuple[list[dict[str, str]], bool]:
    results: list[dict[str, str]] = []
    passed = True
    for check in task["acceptance_checks"]:
        kind = check["kind"]
        if kind == "file_exists":
            path = _inside(workspace, workspace / check["expectation"])
            ok = path.is_file()
            results.append(
                {
                    "check_id": check["check_id"],
                    "status": "passed" if ok else "failed",
                    "detail": f"文件 {'存在' if ok else '不存在'}：{path.relative_to(run_dir)}",
                }
            )
            passed = passed and ok
        else:
            results.append(
                {
                    "check_id": check["check_id"],
                    "status": "not_evaluated",
                    "detail": f"候选 Executor 不负责 {kind}；必须由 Collector/Validator 复核。",
                }
            )
    return results, passed


def _build_blocker(
    spec: Mapping[str, Any],
    task_id: str,
    spec_sha256: str,
    blocker_type: str,
    message: str,
    *,
    retryable: bool,
    recommended_action: str,
    stdout_ref: str | None = None,
    stderr_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "executor_blocker",
        "run_id": spec["run_id"],
        "task_id": task_id,
        "execution_spec_sha256": spec_sha256,
        "blocker_type": blocker_type,
        "message": message,
        "stdout_ref": stdout_ref,
        "stderr_ref": stderr_ref,
        "observed_at": _utc_now(),
        "retryable": retryable,
        "recommended_action": recommended_action,
    }


def execute_spec(spec_path: Path, run_dir: Path, executor_id: str) -> dict[str, Any]:
    """执行候选任务；不会修改 Gate、结果报告或已批准的执行合同。"""
    run_dir = run_dir.resolve()
    spec_path = _safe_spec_file(spec_path, run_dir)
    spec_raw = spec_path.read_bytes()
    spec = _load_object(spec_path)
    _validate(spec, SPEC_SCHEMA_PATH, "execution_spec")
    validate_execution_spec_paths(spec)
    validate_execution_command_bindings(spec, run_dir)
    spec_sha256 = _sha256_bytes(spec_raw)
    resolved_runner = Path(sys.executable).resolve(strict=True)
    resolved_runner_sha256 = _sha256_bytes(resolved_runner.read_bytes())

    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Run 缺少 run_manifest.json")
    manifest = _load_object(manifest_path)
    for field in IMMUTABLE_IDENTITY_FIELDS:
        if manifest.get(field) != spec.get(field):
            raise ValueError(f"execution_spec.{field} 与 Run 不可变身份不一致")

    workspace = _inside(run_dir, run_dir / spec["declared_workspace"])
    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir = run_dir / "candidate_execution_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    task_executions: list[dict[str, Any]] = []
    blocker: dict[str, Any] | None = None
    completed_task_ids: set[str] = set()

    for task in spec["tasks"]:
        task_id = task["task_id"]
        if not set(task["depends_on"]).issubset(completed_task_ids):
            blocker = _build_blocker(
                spec, task_id, spec_sha256, "dependency_failure", "前置任务尚未成功完成。",
                retryable=False, recommended_action="revise_contract"
            )
            break
        cwd = _task_working_directory(task, workspace, run_dir)
        cwd.mkdir(parents=True, exist_ok=True)
        _resolve_approved_command(task, workspace, cwd)
        try:
            input_refs = _check_inputs(task, run_dir)
        except (OSError, ValueError) as exc:
            blocker = _build_blocker(
                spec, task_id, spec_sha256, "missing_input", str(exc),
                retryable=False, recommended_action="revise_contract"
            )
            break

        for seed in task["seed_policy"]["seeds"]:
            execution_id = f"{task_id}-{seed}-{uuid.uuid4().hex[:12]}"
            stdout_path = logs_dir / f"{execution_id}.stdout.log"
            stderr_path = logs_dir / f"{execution_id}.stderr.log"
            task_started_at = _utc_now()
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = str(seed)
            environment["SHUMO_EXECUTION_SEED"] = str(seed)
            try:
                # 合同只授权固定 runner token；实际解释器由 Executor 自身绑定。
                completed = run_process_tree(
                    [str(resolved_runner), *task["argv"][1:]],
                    cwd=cwd,
                    env=environment,
                    capture_output=True,
                    timeout=task["timeout_seconds"],
                    check=False,
                )
                stdout_path.write_bytes(completed.stdout)
                stderr_path.write_bytes(completed.stderr)
                exit_code: int | None = completed.returncode
            except ProcessTreeTimeoutExpired as exc:
                stdout_path.write_bytes(exc.stdout or b"")
                stderr_path.write_bytes(exc.stderr or b"")
                exit_code = None
                blocker = _build_blocker(
                    spec,
                    task_id,
                    spec_sha256,
                    "timeout",
                    (
                        f"任务超过 {task['timeout_seconds']} 秒时限；"
                        f"进程树清理={'通过' if exc.process_tree_terminated else '失败'}。"
                    ),
                    retryable=exc.process_tree_terminated,
                    recommended_action=(
                        "human_review" if exc.process_tree_terminated else "stop_run"
                    ),
                    stdout_ref=_file_ref(stdout_path, run_dir)["path"],
                    stderr_ref=_file_ref(stderr_path, run_dir)["path"],
                )
            except OSError as exc:
                stdout_path.write_bytes(b"")
                stderr_path.write_text(str(exc), encoding="utf-8")
                exit_code = None
                blocker = _build_blocker(
                    spec, task_id, spec_sha256, "command_failed", str(exc),
                    retryable=False, recommended_action="revise_contract",
                    stdout_ref=_file_ref(stdout_path, run_dir)["path"],
                    stderr_ref=_file_ref(stderr_path, run_dir)["path"],
                )

            # 输出路径由合同声明。缺失输出被记录为 acceptance 失败，而不是伪造文件。
            output_refs = []
            for item in task["required_outputs"]:
                output_path = _inside(
                    workspace, run_dir.joinpath(*PurePosixPath(item["path"]).parts)
                )
                if output_path.is_file():
                    output_refs.append(_file_ref(output_path, run_dir))
            acceptance, acceptance_passed = _check_acceptance(task, workspace, run_dir)
            task_executions.append(
                {
                    "execution_id": execution_id,
                    "task_id": task_id,
                    "seed": seed,
                    "argv": task["argv"],
                    "working_directory": cwd.relative_to(run_dir).as_posix(),
                    "started_at": task_started_at,
                    "completed_at": _utc_now(),
                    "exit_code": exit_code,
                    "stdout": _file_ref(stdout_path, run_dir),
                    "stderr": _file_ref(stderr_path, run_dir),
                    "inputs": input_refs,
                    "outputs": output_refs,
                    "acceptance_checks": acceptance,
                }
            )
            if blocker is not None:
                break
            if exit_code != 0:
                blocker = _build_blocker(
                    spec, task_id, spec_sha256, "command_failed", f"命令退出码为 {exit_code}。",
                    retryable=True, recommended_action="human_review",
                    stdout_ref=_file_ref(stdout_path, run_dir)["path"],
                    stderr_ref=_file_ref(stderr_path, run_dir)["path"],
                )
                break
            if not acceptance_passed:
                blocker = _build_blocker(
                    spec, task_id, spec_sha256, "acceptance_check_failed", "候选执行未满足可自动检查的验收条件。",
                    retryable=False, recommended_action="revise_contract",
                    stdout_ref=_file_ref(stdout_path, run_dir)["path"],
                    stderr_ref=_file_ref(stderr_path, run_dir)["path"],
                )
                break
        if blocker is not None:
            break
        completed_task_ids.add(task_id)

    if blocker is None and spec_path.read_bytes() != spec_raw:
        blocker = _build_blocker(
            spec,
            "CONTRACT",
            spec_sha256,
            "authorization_denied",
            "候选执行期间 execution_spec.json 被修改；该候选结果不可接受。",
            retryable=False,
            recommended_action="stop_run",
        )
    if blocker is None:
        for task in spec["tasks"]:
            try:
                _check_inputs(task, run_dir)
            except (OSError, ValueError) as exc:
                blocker = _build_blocker(
                    spec,
                    task["task_id"],
                    spec_sha256,
                    "authorization_denied",
                    f"候选执行后输入材料发生漂移：{exc}",
                    retryable=False,
                    recommended_action="stop_run",
                )
                break

    blocker_ref: str | None = None
    if blocker is not None:
        _validate(blocker, BLOCKER_SCHEMA_PATH, "executor_blocker")
        blocker_path = run_dir / "executor_blocker.json"
        _write_json(blocker_path, blocker)
        blocker_ref = blocker_path.relative_to(run_dir).as_posix()
    record = {
        "schema_version": "1.0.0",
        "artifact_type": "candidate_execution_record",
        "run_id": spec["run_id"],
        "execution_spec_sha256": spec_sha256,
        "executor_id": executor_id,
        "execution_mode": spec["execution_mode"],
        "status": "blocked" if blocker is not None else "completed",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "environment": {
            "python": sys.version,
            "runner_token": "python",
            "resolved_runner": str(resolved_runner),
            "resolved_runner_sha256": resolved_runner_sha256,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cwd": str(run_dir),
        },
        "task_executions": task_executions,
        "blocker_ref": blocker_ref,
        "formal_result_activation_status": "code_complete_candidate",
        "sandboxie_environment_observed": False,
        "sandboxie_environment_verified": False,
        "formal_result_executed_in_verified_environment": False,
        "formal_result_eligible": False,
        "execution_trust_model": spec["execution_mode"],
        "formal_result_authority": (
            "none_rehearsal"
            if spec["formal_result_policy"] == "rehearsal_unqualified_v1"
            else "collector_required"
        ),
    }
    _validate(record, RECORD_SCHEMA_PATH, "candidate_execution_record")
    _write_json(run_dir / "candidate_execution_record.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="执行已批准的数模候选代码合同")
    parser.add_argument("--spec", required=True, type=Path, help="execution_spec.json")
    parser.add_argument("--run-dir", required=True, type=Path, help="运行目录")
    parser.add_argument("--executor-id", required=True, help="执行器身份，例如 codex-local")
    args = parser.parse_args()
    record = execute_spec(args.spec, args.run_dir, args.executor_id)
    print(json.dumps({"status": record["status"], "record": "candidate_execution_record.json"}, ensure_ascii=False))
    return 0 if record["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
