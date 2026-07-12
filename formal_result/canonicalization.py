"""JSON 语义规范化。"""

from __future__ import annotations

import json
import math
from typing import Any


CANONICALIZATION_VERSION = "1.0.0"
# 兼容旧验证报告字段；语义身份哈希本身不再按该精度量化。
CANONICALIZATION_PRECISION = 8


def _normalize(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("规范 JSON 禁止 NaN 和 Infinity")
        return value
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON 对象键必须是字符串")
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        # 数组顺序属于语义，不得为获得稳定哈希而自动重排。
        return [_normalize(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    """生成精确保留 JSON 数值的规范字节：UTF-8、键排序、无多余空白。"""
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
