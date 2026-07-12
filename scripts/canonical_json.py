"""正式输出使用的稳定 JSON 规范化与哈希。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.canonicalization import (
    CANONICALIZATION_PRECISION,
    CANONICALIZATION_VERSION,
    canonical_bytes,
)
from formal_result.hashing import semantic_sha256

def canonical_sha256(value: Any) -> str:
    """兼容旧 Collector 的命名，实际返回 v1.0.0 语义哈希。"""
    return semantic_sha256(value)
