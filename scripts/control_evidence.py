"""从对照审核与已验证运行证据现场派生控制结果。"""

from __future__ import annotations

from typing import Any, Mapping


CONTROL_RESULTS = {"pending", "pass", "fail", "invalid", "needs_retest"}


def derive_control_result(
    control: Mapping[str, Any],
    review: Mapping[str, Any] | None,
    *,
    evidence_valid: bool,
) -> str:
    """派生单类控制结论；矩阵中的手填 result 字段不参与判断。"""
    if "result" in control:
        raise ValueError("控制矩阵不得保存手填 result；结论必须从证据现场派生")
    if not control.get("evidence") or review is None:
        return "pending"
    conclusion = review.get("final_conclusion")
    if conclusion not in CONTROL_RESULTS - {"pending"}:
        return "invalid"
    if not evidence_valid:
        return "invalid"
    if conclusion != "pass":
        return str(conclusion)
    consistency = review.get("consistency_checks")
    if not isinstance(consistency, Mapping) or not consistency:
        return "invalid"
    if any(value is not True for value in consistency.values()):
        return "invalid"
    risks = review.get("risk_items")
    if not isinstance(risks, list) or not risks:
        return "invalid"
    if any(not isinstance(item, Mapping) or item.get("observed") is not False for item in risks):
        return "fail"
    return "pass"
