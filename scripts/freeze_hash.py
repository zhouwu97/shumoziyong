"""冻结组件的跨平台规范字节与哈希。"""

from __future__ import annotations

import hashlib
from pathlib import Path


TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
    ".in",
    ".lock",
}


def canonical_file_bytes(path: Path) -> bytes:
    """文本冻结为 UTF-8 无 BOM、LF；其他文件保留原始字节。"""
    raw = path.read_bytes()
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return raw
    text = raw.decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def canonical_file_sha256(path: Path) -> str:
    return hashlib.sha256(canonical_file_bytes(path)).hexdigest()
