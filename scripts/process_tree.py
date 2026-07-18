"""带完整进程树清理证明的子进程执行工具。"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any, cast

if os.name == "nt":  # pragma: win32 cover
    import ctypes
    from ctypes import wintypes

    _CREATE_SUSPENDED = 0x00000004
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operation_count", ctypes.c_uint64),
            ("write_operation_count", ctypes.c_uint64),
            ("other_operation_count", ctypes.c_uint64),
            ("read_transfer_count", ctypes.c_uint64),
            ("write_transfer_count", ctypes.c_uint64),
            ("other_transfer_count", ctypes.c_uint64),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_int64),
            ("per_job_user_time_limit", ctypes.c_int64),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", _BasicLimitInformation),
            ("io_info", _IoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]

    class _BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("total_user_time", ctypes.c_int64),
            ("total_kernel_time", ctypes.c_int64),
            ("this_period_total_user_time", ctypes.c_int64),
            ("this_period_total_kernel_time", ctypes.c_int64),
            ("total_page_fault_count", wintypes.DWORD),
            ("total_processes", wintypes.DWORD),
            ("active_processes", wintypes.DWORD),
            ("total_terminated_processes", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long


    class _WindowsJob:
        """用 Job Object 为一次命令提供不可逃逸的进程树生命周期。"""

        def __init__(self) -> None:
            self.handle = _kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimitInformation()
            limits.basic_limit_information.limit_flags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            if not _kernel32.SetInformationJobObject(
                self.handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error

        def assign_and_resume(self, process: subprocess.Popen[Any]) -> None:
            process_handle = cast(Any, process)._handle
            if not _kernel32.AssignProcessToJobObject(self.handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
            status = _ntdll.NtResumeProcess(process_handle)
            if status != 0:
                raise OSError(f"NtResumeProcess 失败，NTSTATUS=0x{status & 0xFFFFFFFF:08x}")

        def active_processes(self) -> int:
            accounting = _BasicAccountingInformation()
            if not _kernel32.QueryInformationJobObject(
                self.handle,
                _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                ctypes.byref(accounting),
                ctypes.sizeof(accounting),
                None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(accounting.active_processes)

        def terminate(self, process: subprocess.Popen[Any]) -> tuple[bool, dict[str, Any]]:
            details: dict[str, Any] = {"method": "windows_job_object"}
            terminated = bool(_kernel32.TerminateJobObject(self.handle, 1))
            if not terminated:
                details["terminate_error"] = str(ctypes.WinError(ctypes.get_last_error()))
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                details["parent_wait_timed_out"] = True

            deadline = time.monotonic() + 5
            active: int | None = None
            while time.monotonic() < deadline:
                try:
                    active = self.active_processes()
                except OSError as exc:
                    details["query_error"] = str(exc)
                    break
                if active == 0:
                    break
                time.sleep(0.05)
            details["active_processes_after_cleanup"] = active
            details["direct_process_return_code"] = process.returncode
            proven = terminated and active == 0 and process.returncode is not None
            details["process_tree_terminated"] = proven
            return proven, details

        def close(self) -> None:
            if self.handle:
                _kernel32.CloseHandle(self.handle)
                self.handle = None


class ProcessTreeTimeoutExpired(subprocess.TimeoutExpired):
    """命令超时，并携带进程树清理结果。"""

    def __init__(
        self,
        cmd: Sequence[str],
        timeout: float,
        *,
        output: str | bytes | None,
        stderr: str | bytes | None,
        process_tree_terminated: bool,
        termination_details: Mapping[str, Any],
    ) -> None:
        super().__init__(cmd, timeout, output=output, stderr=stderr)
        self.process_tree_terminated = process_tree_terminated
        self.termination_details = dict(termination_details)


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
        process.wait(timeout=2)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        details["escalated_to_sigkill"] = True
        try:
            kill_process_group(process_group, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            pass
        process.wait(timeout=5)

    try:
        kill_process_group(process_group, 0)
    except ProcessLookupError:
        terminated = True
    else:
        terminated = False
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
    if input is not None:
        stdin = subprocess.PIPE
    else:
        stdin = None
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
    windows_job = None
    if os.name == "nt":
        windows_job = _WindowsJob()
        popen_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED
        )
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(list(args), **popen_options)
    if windows_job is not None:
        try:
            windows_job.assign_and_resume(process)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            windows_job.close()
            raise
    try:
        output, error_output = process.communicate(
            input=cast(Any, input), timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        if windows_job is not None:
            terminated, details = windows_job.terminate(process)
        else:
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
        if windows_job is not None:
            windows_job.terminate(process)
        else:
            terminate_process_tree(process)
        raise
    finally:
        if windows_job is not None:
            windows_job.close()

    completed = subprocess.CompletedProcess(args, process.returncode, output, error_output)
    if check:
        completed.check_returncode()
    return completed
