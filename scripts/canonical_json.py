"""正式输出使用的稳定 JSON 规范化与哈希。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any


CANONICALIZATION_VERSION = "1.0.0"
CANONICALIZATION_PRECISION = 8
FLOAT_QUANTUM = Decimal("0.00000001")


def _normalise(value: Any) -> Any:
    if isinstance(value, float):
        return float(Decimal(str(value)).quantize(FLOAT_QUANTUM, rounding=ROUND_HALF_EVEN))
    if isinstance(value, dict):
        return {key: _normalise(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return [_normalise(item) for item in sorted(value, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))]
        return [_normalise(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    """仅用于证据身份；调用者必须先以原始数值完成数学验证。"""
    return (json.dumps(_normalise(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
