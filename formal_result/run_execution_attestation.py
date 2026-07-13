"""Run 专属 Sandboxie 执行证明的失败即关闭验证。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .canonicalization import canonical_bytes
from .errors import FormalResultVerificationError
from .hashing import file_sha256, semantic_sha256
from .derivation import verify_formal_result_derivation
from .execution_contract import (
    compile_execution_command,
    launch_command_sha256,
    sandbox_policy_sha256,
)
from .sandboxie_environment import (
    TRUST_REGISTRY_PATH,
    _parse_time,
    _verify_rsa_signature,
    load_and_verify_sandboxie_environment_report,
)
from .schema import validate_schema
from .runtime_isolation import (
    ALLOWED_READ_ROOTS,
    ALLOWED_WRITE_ROOTS,
    READ_ISOLATION_MODE,
    RUNTIME_MANIFEST_FILENAME,
    SYSTEM_RUNTIME_READ_ROOTS,
    verify_default_deny_roots,
    verify_runtime_manifest,
)


ATTESTATION_FILENAME = "sandboxie_run_execution_attestation.json"
OUTPUT_MANIFEST_FILENAME = "run_output_manifest.json"
EXECUTION_RECORD_FILENAME = "sandboxie_run_execution_record.json"
TRANSIENT_START_EXIT = 0x40010004


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalResultVerificationError(f"{label} 无法作为严格 UTF-8 JSON 读取：{exc}") from exc
    if not isinstance(value, dict):
        raise FormalResultVerificationError(f"{label} 必须是 JSON 对象")
    return value


def _regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise FormalResultVerificationError(f"{label} 必须是普通文件")
    if os.stat(path, follow_symlinks=False).st_nlink != 1:
        raise FormalResultVerificationError(f"{label} 禁止 hardlink")


def _exact_manifest_files(root: Path, items: Any, label: str) -> None:
    if not isinstance(items, list):
        raise FormalResultVerificationError(f"{label}.files 必须是数组")
    declared: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise FormalResultVerificationError(f"{label} 包含非法文件项")
        relative = item["path"]
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise FormalResultVerificationError(f"{label} 包含非法路径")
        path = root.joinpath(*Path(relative).parts)
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise FormalResultVerificationError(f"{label} 路径越界：{relative}") from exc
        _regular_file(path, f"{label} 文件 {relative}")
        if relative in declared or file_sha256(path) != item["sha256"]:
            raise FormalResultVerificationError(f"{label} 文件重复或 SHA 不匹配：{relative}")
        declared[relative] = item["sha256"]
    for path in root.rglob("*"):
        is_junction = getattr(path, "is_junction", lambda: False)
        if path.is_symlink() or is_junction():
            raise FormalResultVerificationError(f"{label} 禁止 symlink 或 junction：{path}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if set(declared) != actual:
        raise FormalResultVerificationError(
            f"{label} 精确文件集不匹配：声明 {sorted(declared)}，实际 {sorted(actual)}"
        )


def _relative_items(items: Any, prefix: str, label: str) -> list[dict[str, str]]:
    """把 Run 相对清单转换为物化目录相对清单，并拒绝越出固定前缀。"""
    if not isinstance(items, list):
        raise FormalResultVerificationError(f"{label} 必须是数组")
    converted: list[dict[str, str]] = []
    marker = prefix.rstrip("/") + "/"
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise FormalResultVerificationError(f"{label} 包含非法文件项")
        path = item["path"]
        if not path.startswith(marker):
            raise FormalResultVerificationError(f"{label} 文件不在 {prefix} 下：{path}")
        sha256 = item.get("sha256")
        if not isinstance(sha256, str):
            raise FormalResultVerificationError(f"{label} 文件缺少 SHA-256：{path}")
        converted.append({"path": path.removeprefix(marker), "sha256": sha256})
    return converted


def validate_execution_time_window(
    generated_at: str, started_at: str, completed_at: str, valid_until: str
) -> None:
    """要求 Run 从开始到完成都落入环境证明有效窗口。"""
    generated = _parse_time(generated_at, "environment.generated_at")
    started = _parse_time(started_at, "started_at")
    completed = _parse_time(completed_at, "completed_at")
    valid = _parse_time(valid_until, "environment.valid_until")
    if not generated <= started <= completed <= valid:
        raise FormalResultVerificationError("Run 执行时间窗口非法")


def verify_run_execution_attestation(
    run_root: Path,
    formal_result_id: str,
    *,
    require_current_environment: bool = False,
    registry_path: Path = TRUST_REGISTRY_PATH,
) -> dict[str, Any]:
    """验证 Run 身份、完整现场、环境信任链和机器签名。"""
    run_root = run_root.resolve()
    paths = {
        "run_manifest": run_root / "run_manifest.json",
        "execution_spec": run_root / "execution_spec.json",
        "report": run_root / "sandboxie_environment_report.json",
        "environment_attestation": run_root / "sandboxie_environment_attestation.json",
        "attestation": run_root / ATTESTATION_FILENAME,
        "output_manifest": run_root / OUTPUT_MANIFEST_FILENAME,
        "execution_record": run_root / EXECUTION_RECORD_FILENAME,
        "runtime_manifest": run_root / RUNTIME_MANIFEST_FILENAME,
    }
    for label, path in paths.items():
        _regular_file(path, label)
    summary = load_and_verify_sandboxie_environment_report(
        paths["report"], paths["environment_attestation"], registry_path
    )
    environment_report = _load_object(paths["report"], "Sandboxie 环境报告")
    if require_current_environment and not summary["environment_attestation_currently_valid"]:
        raise FormalResultVerificationError("环境报告已过期，禁止启动新的 Run 执行")

    attestation = _load_object(paths["attestation"], "Run Execution Attestation")
    validate_schema(
        attestation,
        "sandboxie_run_execution_attestation.schema.json",
        "Run Execution Attestation",
    )
    run_manifest = _load_object(paths["run_manifest"], "run_manifest.json")
    spec = _load_object(paths["execution_spec"], "execution_spec.json")
    record = _load_object(paths["execution_record"], EXECUTION_RECORD_FILENAME)
    output_manifest = _load_object(paths["output_manifest"], OUTPUT_MANIFEST_FILENAME)
    derivation_summary = verify_formal_result_derivation(run_root, formal_result_id)
    formal_root = run_root / "formal_results" / formal_result_id
    code_manifest_path = formal_root / "code_manifest.json"
    input_manifest_path = formal_root / "input_manifest.json"
    for label, path in (("code_manifest", code_manifest_path), ("input_manifest", input_manifest_path)):
        _regular_file(path, label)

    expected = {
        "run_id": run_manifest.get("run_id"),
        "formal_result_id": formal_result_id,
        "execution_spec_sha256": file_sha256(paths["execution_spec"]),
        "run_manifest_sha256": file_sha256(paths["run_manifest"]),
        "code_manifest_sha256": file_sha256(code_manifest_path),
        "input_manifest_sha256": file_sha256(input_manifest_path),
        "output_manifest_sha256": file_sha256(paths["output_manifest"]),
        "execution_record_sha256": file_sha256(paths["execution_record"]),
        "runtime_manifest_sha256": file_sha256(paths["runtime_manifest"]),
        "formal_result_payload_manifest_sha256": derivation_summary[
            "payload_manifest_sha256"
        ],
        "collector_derivation_attestation_sha256": derivation_summary[
            "collector_derivation_attestation_sha256"
        ],
        "formal_result_core_digest": derivation_summary["formal_result_core_digest"],
        "environment_report_sha256": summary["report_file_sha256"],
        "environment_attestation_sha256": summary["attestation_file_sha256"],
        "trusted_registry_sha256": summary["trusted_registry_sha256"],
        "trusted_key_entry_semantic_sha256": summary["trusted_key_entry_semantic_sha256"],
        "environment_fingerprint": summary["environment_fingerprint"],
        "machine_key_id": summary["machine_key_id"],
    }
    for field, value in expected.items():
        if attestation.get(field) != value:
            raise FormalResultVerificationError(f"Run Execution Attestation 绑定不匹配：{field}")
    report_start_sha = next(
        item["file_sha256"]
        for item in environment_report["installation"]["components"]
        if item["role"] == "start_exe"
    )
    if attestation["start_exe_sha256"] != report_start_sha:
        raise FormalResultVerificationError("Run Execution Attestation 的 Start.exe SHA 与环境报告不一致")
    if spec.get("run_id") != attestation["run_id"] or record.get("run_id") != attestation["run_id"]:
        raise FormalResultVerificationError("Run ID 不匹配")
    if record.get("formal_result_id") != formal_result_id:
        raise FormalResultVerificationError("Formal Result ID 不匹配")
    if record.get("execution_id") != derivation_summary["execution_id"]:
        raise FormalResultVerificationError("执行记录与 Formal Result 派生 execution_id 不匹配")
    for field in (
        "execution_id", "sandboxie_box_name", "sandbox_policy_sha256", "launch_command_sha256", "started_at",
        "completed_at", "exit_code", "stdout_sha256", "stderr_sha256", "start_exe_sha256",
        "challenge_nonce",
    ):
        if record.get(field) != attestation.get(field):
            raise FormalResultVerificationError(f"执行记录绑定不匹配：{field}")
    if record.get("sandboxie_marker_detected") is not True:
        raise FormalResultVerificationError("未证明进程在 Sandboxie 内执行")
    compiled = compile_execution_command(
        spec,
        run_root / "execution_sandbox",
        execution_id=attestation["execution_id"],
        challenge_nonce=attestation["challenge_nonce"],
    )
    for field in (
        "resolved_argv",
        "resolved_working_directory",
        "seed",
        "environment_overrides",
    ):
        if record.get(field) != compiled[field]:
            raise FormalResultVerificationError(f"执行记录未遵循 Execution Spec：{field}")
    policy_settings = record.get("sandbox_policy_settings")
    if not isinstance(policy_settings, list) or not all(
        isinstance(item, str) for item in policy_settings
    ):
        raise FormalResultVerificationError("Sandboxie 策略记录非法")
    recomputed_policy_sha = sandbox_policy_sha256(policy_settings)
    if record.get("sandbox_policy_sha256") != recomputed_policy_sha or attestation.get(
        "sandbox_policy_sha256"
    ) != recomputed_policy_sha:
        raise FormalResultVerificationError("sandbox_policy_sha256 无法由实际策略复算")
    python_sha = record.get("python_sha256")
    if not isinstance(python_sha, str) or len(python_sha) != 64:
        raise FormalResultVerificationError("执行记录缺少 Python 解释器 SHA-256")
    requirements_lock = Path(__file__).resolve().parents[1] / "requirements.lock"
    if record.get("requirements_lock_sha256") != file_sha256(requirements_lock):
        raise FormalResultVerificationError("执行记录 requirements.lock SHA-256 不匹配")
    runtime_manifest = _load_object(paths["runtime_manifest"], RUNTIME_MANIFEST_FILENAME)
    verify_runtime_manifest(runtime_manifest)
    runtime_manifest_sha = file_sha256(paths["runtime_manifest"])
    if record.get("runtime_manifest_sha256") != runtime_manifest_sha:
        raise FormalResultVerificationError("执行记录未绑定 Runtime Manifest")
    if runtime_manifest.get("requirements_lock_sha256") != file_sha256(requirements_lock):
        raise FormalResultVerificationError("Runtime Manifest 未绑定 requirements.lock")
    if runtime_manifest.get("files"):
        executable_entry = next(
            (
                item
                for item in runtime_manifest["files"]
                if item["path"] == runtime_manifest["python_executable_path"]
            ),
            None,
        )
        if executable_entry is None or executable_entry["sha256"] != python_sha:
            raise FormalResultVerificationError("Runtime Manifest 中的 Python SHA 不匹配")
    recomputed_launch_sha = launch_command_sha256(
        compiled,
        start_exe_sha256=attestation["start_exe_sha256"],
        python_sha256=python_sha,
        runtime_manifest_sha256=runtime_manifest_sha,
        sandboxie_box_name=attestation["sandboxie_box_name"],
    )
    if record.get("launch_command_sha256") != recomputed_launch_sha or attestation.get(
        "launch_command_sha256"
    ) != recomputed_launch_sha:
        raise FormalResultVerificationError("launch_command_sha256 未绑定 Execution Spec 编译结果")
    denied_roots = verify_default_deny_roots(record.get("denied_host_roots"))
    if record.get("read_isolation_mode") != READ_ISOLATION_MODE:
        raise FormalResultVerificationError("Run 读取隔离未声明为 default_deny")
    if record.get("allowed_read_roots") != ALLOWED_READ_ROOTS:
        raise FormalResultVerificationError("Run 读取白名单与固定策略不一致")
    if record.get("allowed_write_roots") != ALLOWED_WRITE_ROOTS:
        raise FormalResultVerificationError("Run 写入白名单与固定策略不一致")
    if record.get("system_runtime_read_roots") != SYSTEM_RUNTIME_READ_ROOTS:
        raise FormalResultVerificationError("Privacy Mode 系统 Runtime 根声明不一致")
    required_policy = {
        "UsePrivacyMode=y",
        "UseRuleSpecificity=y",
        "HideMessage=2203",
        *(f"ReadFilePath=%EXECUTION_ROOT%\\{item}" for item in ALLOWED_READ_ROOTS),
        *(f"OpenFilePath=%EXECUTION_ROOT%\\{item}" for item in ALLOWED_WRITE_ROOTS),
    }
    if not denied_roots or not required_policy.issubset(
        set(record.get("sandbox_policy_settings", []))
    ):
        raise FormalResultVerificationError("Sandboxie 策略未形成批准目录与宿主读取负控边界")
    controls = record.get("read_negative_controls")
    required_controls = {
        "blocked_read_original_run",
        "blocked_read_repo_unlisted",
        "blocked_read_other_temp",
        "blocked_read_user_home",
        "blocked_read_random_unregistered_host_file",
    }
    if not isinstance(controls, list) or {
        item.get("control_id") for item in controls if isinstance(item, Mapping)
    } != required_controls or any(
        not isinstance(item, Mapping)
        or item.get("status") != "passed"
        or item.get("exit_code") != 0
        or not isinstance(item.get("attempt_exit_codes"), list)
        or not item["attempt_exit_codes"]
        or item["attempt_exit_codes"][-1] != 0
        or any(code != TRANSIENT_START_EXIT for code in item["attempt_exit_codes"][:-1])
        for item in controls
    ):
        raise FormalResultVerificationError("Run 外宿主读取负控未精确通过")
    candidate_attempts = record.get("candidate_attempt_exit_codes")
    if not isinstance(candidate_attempts, list) or not candidate_attempts or (
        candidate_attempts[-1] != 0
        or any(code != TRANSIENT_START_EXIT for code in candidate_attempts[:-1])
    ):
        raise FormalResultVerificationError("候选命令启动尝试记录非法")
    cleanup = record.get("cleanup")
    if not isinstance(cleanup, Mapping) or not (
        cleanup.get("terminate_exit_code") == 0
        and cleanup.get("delete_exit_code") == 0
        and cleanup.get("box_processes_after") == []
        and cleanup.get("sandbox_paths_after") == []
        and cleanup.get("new_controller_pids_after") == []
        and cleanup.get("configuration_remove_exit_code") == 0
        and cleanup.get("box_configuration_removed") is True
        and cleanup.get("preexisting_configuration_restored") is True
        and cleanup.get("configuration_sections_after")
        == cleanup.get("preexisting_configuration_sections")
    ):
        raise FormalResultVerificationError("Sandboxie 清理证明未通过")
    expected_acceptance = {
        str(check["check_id"]) for check in compiled["acceptance_checks"]
    }
    acceptance = record.get("acceptance_results")
    if not isinstance(acceptance, list) or {
        item.get("check_id") for item in acceptance if isinstance(item, Mapping)
    } != expected_acceptance or any(
        not isinstance(item, Mapping) or item.get("status") != "passed"
        for item in acceptance
    ):
        raise FormalResultVerificationError("Execution Spec acceptance checks 未通过")
    if record.get("undeclared_write_count") != 0 or record.get("code_unchanged") is not True:
        raise FormalResultVerificationError("执行现场存在未声明写入或代码修改")
    if record.get("input_unchanged") is not True or record.get("output_set_exact") is not True:
        raise FormalResultVerificationError("输入发生修改或输出集合不精确")
    validate_execution_time_window(
        summary["generated_at"],
        attestation["started_at"],
        attestation["completed_at"],
        summary["valid_until"],
    )

    archived_output = run_root / "execution_sandbox" / "output"
    stdout_path = archived_output / "stdout.log"
    stderr_path = archived_output / "stderr.log"
    challenge_path = run_root / "workspace" / "output" / "execution_challenge.json"
    for path, field in (
        (stdout_path, "stdout_sha256"),
        (stderr_path, "stderr_sha256"),
        (challenge_path, "execution_challenge_sha256"),
    ):
        _regular_file(path, field)
        if record.get(field) != file_sha256(path):
            raise FormalResultVerificationError(f"执行记录日志或 challenge SHA 不匹配：{field}")
    challenge_echo = _load_object(challenge_path, "execution_challenge.json")
    if challenge_echo != {
        "challenge_nonce": attestation["challenge_nonce"],
        "run_id": attestation["run_id"],
        "execution_id": attestation["execution_id"],
    }:
        raise FormalResultVerificationError("Execution Challenge 未由候选进程正确回显")

    code_manifest = _load_object(code_manifest_path, "code_manifest.json")
    workspace = run_root / str(spec["declared_workspace"])
    code_files = _relative_items(
        code_manifest.get("payload", {}).get("files"),
        f"{spec['declared_workspace']}/code",
        "Code Manifest",
    )
    _exact_manifest_files(workspace / "code", code_files, "Code Manifest")
    input_manifest = _load_object(input_manifest_path, "input_manifest.json")
    input_files = _relative_items(
        input_manifest.get("payload", {}).get("inputs"), "problem", "Input Manifest"
    )
    unique_inputs = {item["path"]: item for item in input_files}
    if len(unique_inputs) != len(input_files):
        input_files = list(unique_inputs.values())
    _exact_manifest_files(run_root / "problem", input_files, "Input Manifest")
    _exact_manifest_files(run_root / "workspace" / "output", output_manifest.get("files"), "Output Manifest")

    registry = _load_object(registry_path, "可信环境注册表")
    key = next(
        (item for item in registry["keys"] if item["machine_key_id"] == attestation["machine_key_id"]),
        None,
    )
    if key is None or semantic_sha256(key) != attestation["trusted_key_entry_semantic_sha256"]:
        raise FormalResultVerificationError("可信 Key 条目发生变化")
    unsigned = dict(attestation)
    signature = str(unsigned.pop("signature"))
    _verify_rsa_signature(canonical_bytes(unsigned), signature, key)
    currently_valid = _parse_time(summary["valid_until"], "valid_until") >= datetime.now(timezone.utc)
    return {
        **expected,
        "execution_id": attestation["execution_id"],
        "run_attestation_file_sha256": file_sha256(paths["attestation"]),
        "run_attestation_semantic_sha256": semantic_sha256(attestation),
        "environment_verified_at_generation": True,
        "environment_attestation_currently_valid": currently_valid,
        "formal_result_activation_status": "run_execution_verified",
        "sandboxie_environment_observed": True,
        "sandboxie_environment_verified": True,
        "formal_result_executed_in_verified_environment": True,
        "formal_result_eligible": True,
    }
