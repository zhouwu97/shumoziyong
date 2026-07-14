"""Gate 3 复核器语义合同的最小测试夹具。"""

from __future__ import annotations


def contract_fixture_marker() -> str:
    """标识该校验器可由配套合同声明其检查语义。"""
    return "gate3-evidence-fixture-v1"
