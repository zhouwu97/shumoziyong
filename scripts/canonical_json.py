"""旧 M2 数值结果的容差等价摘要；不得用作 Formal Result 语义身份哈希。"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.canonicalization import (
    CANONICALIZATION_PRECISION,
    CANONICALIZATION_VERSION,
    canonical_bytes,
)


_FLOAT_QUANTUM = Decimal("0.00000001")


def _normalize_equivalent_result(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("结果等价摘要禁止 NaN 和 Infinity")
        return float(Decimal(str(value)).quantize(_FLOAT_QUANTUM, rounding=ROUND_HALF_EVEN))
    if isinstance(value, dict):
        return {key: _normalize_equivalent_result(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_equivalent_result(item) for item in value]
    return value


def result_equivalence_sha256(value: Any) -> str:
    """按固定 8 位小数容差生成旧 M2 结果等价摘要。"""
    payload = json.dumps(
        _normalize_equivalent_result(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    """兼容旧 Collector 名称；新代码应使用 result_equivalence_sha256。"""
    return result_equivalence_sha256(value)
