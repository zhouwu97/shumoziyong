"""JSON 语义规范化。"""

from __future__ import annotations

import json
import math
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any


CANONICALIZATION_VERSION = "1.0.0"
CANONICALIZATION_PRECISION = 8
_FLOAT_QUANTUM = Decimal("0.00000001")


def _normalize(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("规范 JSON 禁止 NaN 和 Infinity")
        return float(Decimal(str(value)).quantize(_FLOAT_QUANTUM, rounding=ROUND_HALF_EVEN))
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON 对象键必须是字符串")
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        # 数组顺序属于语义，不得为获得稳定哈希而自动重排。
        return [_normalize(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    """生成 v1.0.0 规范字节：UTF-8、键排序、无空白、无结尾换行。"""
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
