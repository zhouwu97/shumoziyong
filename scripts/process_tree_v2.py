"""通用运行时使用的进程树执行工具。

冻结的 A092 协议继续引用 ``process_tree.py``；本模块承载后续运行时修复，
避免改变历史协议绑定的源码哈希。
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any, cast

from process_tree import ProcessTreeTimeoutExpired


def _wait_for_posix_process_group_exit(
    process_group: int,
    *,
    timeout: float,
    poll_interval: float = 0.05,
) -> bool:
    """在有界时间内确认 POSIX 进程组已经从系统进程表消失。"""
    kill_process_group = getattr(os, "killpg")
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        try:
            kill_process_group(process_group, 0)
        except ProcessLookupError:
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(max(poll_interval, 0), remaining))


def _terminate_windows_tree(process: subprocess.Popen[Any]) -> tuple[bool, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        taskkill_details: dict[str, Any] = {
            "method": "taskkill_tree",
            "taskkill_return_code": result.returncode,
            "taskkill_stdout": result.stdout,
            "taskkill_stderr": result.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        taskkill_details = {
            "method": "taskkill_tree",
            "taskkill_return_code": None,
            "taskkill_error": str(exc),
        }

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        taskkill_details["direct_process_fallback_kill"] = True

    terminated = (
        process.returncode is not None
        and taskkill_details.get("taskkill_return_code") == 0
    )
    taskkill_details["direct_process_return_code"] = process.returncode
    taskkill_details["process_tree_terminated"] = terminated
    return terminated, taskkill_details


def _terminate_posix_tree(process: subprocess.Popen[Any]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"method": "process_group"}
    get_process_group = getattr(os, "getpgid")
    kill_process_group = getattr(os, "killpg")
    try:
        process_group = get_process_group(process.pid)
    except ProcessLookupError:
        details["process_tree_terminated"] = True
        return True, details

    try:
        kill_process_group(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass

    terminated = _wait_for_posix_process_group_exit(process_group, timeout=0.5)
    if not terminated:
        details["escalated_to_sigkill"] = True
        try:
            kill_process_group(process_group, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                details["direct_process_wait_timed_out"] = True
        terminated = _wait_for_posix_process_group_exit(process_group, timeout=5)

    details["direct_process_return_code"] = process.returncode
    details["process_tree_terminated"] = terminated
    return terminated, details


def terminate_process_tree(
    process: subprocess.Popen[Any],
) -> tuple[bool, dict[str, Any]]:
    """终止由本工具启动的进程树，并返回可序列化清理证明。"""
    if os.name == "nt":
        return _terminate_windows_tree(process)
    return _terminate_posix_tree(process)


def run_process_tree(
    args: Sequence[str],
    *,
    input: str | bytes | None = None,
    stdout: int | IO[Any] | None = None,
    stderr: int | IO[Any] | None = None,
    capture_output: bool = False,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    check: bool = False,
    text: bool | None = None,
    encoding: str | None = None,
    errors: str | None = None,
) -> subprocess.CompletedProcess[Any]:
    """在独立进程组中运行命令；超时时先清理完整进程树。"""
    stdin = subprocess.PIPE if input is not None else None
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("capture_output 不能与 stdout/stderr 同时使用")
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE

    popen_options: dict[str, Any] = {
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
        "cwd": cwd,
        "env": env,
        "text": text,
        "encoding": encoding,
        "errors": errors,
        "shell": False,
    }
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(list(args), **popen_options)
    try:
        output, error_output = process.communicate(
            input=cast(Any, input), timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        terminated, details = terminate_process_tree(process)
        final_output, final_error = process.communicate()
        raise ProcessTreeTimeoutExpired(
            args,
            float(timeout or 0),
            output=final_output if final_output is not None else exc.output,
            stderr=final_error if final_error is not None else exc.stderr,
            process_tree_terminated=terminated,
            termination_details=details,
        ) from None
    except BaseException:
        terminate_process_tree(process)
        raise

    completed = subprocess.CompletedProcess(args, process.returncode, output, error_output)
    if check:
        completed.check_returncode()
    return completed
