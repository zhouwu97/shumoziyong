from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _stale_temp_files(path: Path) -> list[Path]:
    """查找同一目标遗留的原子写临时文件。"""
    prefix = f".{path.name}."
    return sorted(
        candidate
        for candidate in path.parent.iterdir()
        if candidate.is_file()
        and candidate.name.startswith(prefix)
        and candidate.name.endswith(".tmp")
    )


def recover_atomic_write(path: Path) -> list[Path]:
    """清理上次中断遗留的临时文件，返回已清理路径。"""
    if not path.parent.is_dir():
        return []
    stale = _stale_temp_files(path)
    for candidate in stale:
        candidate.unlink()
    return stale


def _sync_parent_directory(path: Path) -> None:
    """POSIX 上同步目录项；Windows 的 os.replace 已提供所需原子替换语义。"""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path.parent, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """在目标目录内以 fsync + os.replace 耐崩溃地替换文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    recover_atomic_write(path)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _sync_parent_directory(path)
        if path.read_bytes() != content:
            raise OSError(f"原子写入回读校验失败：{path}")
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """以 UTF-8 原子写入文本。"""
    atomic_write_bytes(path, content.encode("utf-8"))
