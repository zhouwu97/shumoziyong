"""Run 专属 Python Runtime 包与默认拒绝读取边界。"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .errors import FormalResultVerificationError
from .hashing import file_sha256
from .schema import validate_schema


RUNTIME_MANIFEST_FILENAME = "run_execution_runtime_manifest.json"
READ_ISOLATION_MODE = "default_deny"
ALLOWED_READ_ROOTS = [
    "runtime",
    "code",
    "input",
    "execution_spec.json",
    RUNTIME_MANIFEST_FILENAME,
]
ALLOWED_WRITE_ROOTS = ["output", "tmp"]
SYSTEM_RUNTIME_READ_ROOTS = [
    "%SYSTEMROOT%",
    "%PROGRAMFILES%",
    "%PROGRAMFILES_X86%",
    "%PROGRAMDATA%\\Microsoft",
]


def logical_drive_roots() -> list[str]:
    """枚举生成时所有本地盘符根；策略不得只挑选已知敏感目录。"""
    if os.name != "nt":
        raise RuntimeError("默认拒绝 Runtime 打包只支持 Windows Sandboxie 主机")
    mask = int(ctypes.windll.kernel32.GetLogicalDrives())
    roots = [f"{chr(65 + index)}:\\" for index in range(26) if mask & (1 << index)]
    if not roots:
        raise RuntimeError("无法枚举 Windows 逻辑卷根")
    return roots


def _copy_runtime_tree(target: Path) -> Path:
    """物化解释器、标准库和已安装依赖，避免候选读取宿主 Python 树。"""
    source = Path(sys.base_prefix).resolve(strict=True)
    target.mkdir(parents=True, exist_ok=False)
    executable = Path(sys.executable).resolve(strict=True)
    base_executable = source / executable.name
    if not base_executable.is_file():
        candidates = sorted(source.glob("python*.exe"))
        if not candidates:
            raise RuntimeError("Python base_prefix 中缺少可物化解释器")
        base_executable = candidates[0]

    for candidate in source.iterdir():
        name = candidate.name.lower()
        if candidate.is_file() and (
            name.startswith("python") or name.startswith("vcruntime") or name == "ucrtbase.dll"
        ):
            shutil.copy2(candidate, target / candidate.name)
    for directory in ("DLLs", "Lib"):
        source_dir = source / directory
        if source_dir.is_dir():
            shutil.copytree(source_dir, target / directory)
    runtime_executable = target / base_executable.name
    if not runtime_executable.is_file():
        shutil.copy2(base_executable, runtime_executable)
    pth = target / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth.write_text(".\nLib\nLib/site-packages\nimport site\n", encoding="utf-8")
    wrapper = target / "shumo_launch_wrapper.py"
    wrapper.write_text(
        "import ctypes, os, runpy, sys\n"
        "if not ctypes.windll.kernel32.GetModuleHandleW('SbieDll.dll'):\n"
        "    raise SystemExit(97)\n"
        "working_directory, entrypoint, *arguments = sys.argv[1:]\n"
        "os.chdir(working_directory)\n"
        "sys.argv = [entrypoint, *arguments]\n"
        "runpy.run_path(entrypoint, run_name='__main__')\n",
        encoding="utf-8",
    )
    return runtime_executable


def materialize_runtime(target: Path, requirements_lock: Path) -> tuple[Path, dict[str, Any]]:
    runtime_executable = _copy_runtime_tree(target)
    files = [
        {"path": path.relative_to(target).as_posix(), "sha256": file_sha256(path)}
        for path in sorted(target.rglob("*"))
        if path.is_file()
    ]
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "run_execution_runtime_manifest",
        "python_version": sys.version,
        "python_executable_path": runtime_executable.relative_to(target).as_posix(),
        "requirements_lock_sha256": file_sha256(requirements_lock),
        "files": files,
    }
    return runtime_executable, manifest


def verify_runtime_manifest(manifest: Mapping[str, Any]) -> None:
    validate_schema(
        dict(manifest),
        "run_execution_runtime_manifest.schema.json",
        RUNTIME_MANIFEST_FILENAME,
    )
    paths: set[str] = set()
    for item in manifest["files"]:
        raw = str(item["path"])
        pure = PurePosixPath(raw)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise FormalResultVerificationError("Runtime Manifest 含不安全相对路径")
        if raw in paths:
            raise FormalResultVerificationError("Runtime Manifest 文件路径重复")
        paths.add(raw)
    if manifest["python_executable_path"] not in paths:
        raise FormalResultVerificationError("Runtime Manifest 未包含声明的 Python 解释器")


def verify_default_deny_roots(roots: Any) -> list[str]:
    if not isinstance(roots, list) or not roots or not all(isinstance(item, str) for item in roots):
        raise FormalResultVerificationError("denied_host_roots 缺失")
    normalized = sorted(set(roots))
    if len(normalized) != len(roots) or any(
        len(root) != 3 or root[1:] != ":\\" or not root[0].isalpha() for root in roots
    ):
        raise FormalResultVerificationError("denied_host_roots 必须是唯一 Windows 卷根")
    return normalized
