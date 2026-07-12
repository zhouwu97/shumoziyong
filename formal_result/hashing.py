"""文件哈希与语义哈希，两者不得混用。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .canonicalization import canonical_bytes


def file_sha256(path: Path) -> str:
    """对磁盘原始字节计算 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic_sha256(value: Any) -> str:
    """对已经 Schema 校验的 JSON 值计算规范语义 SHA-256。"""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
