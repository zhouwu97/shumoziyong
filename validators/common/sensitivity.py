"""按适用性执行的敏感性证据检查。"""

from __future__ import annotations

from typing import Any, Mapping


def _derive_classification(
    relative_change: float, structure_changed: bool, conclusion_reversed: bool
) -> str:
    magnitude = abs(relative_change)
    if conclusion_reversed or structure_changed or magnitude > 0.15:
        return "highly_sensitive"
    if magnitude > 0.05:
        return "moderately_sensitive"
    return "stable"


def run_sensitivity_checks(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """核验敏感性分类；关闭时要求给出原因和结论影响。"""

    status = evidence.get("status")
    if status == "not_applicable":
        valid = bool(evidence.get("reason")) and bool(evidence.get("impact_on_core_conclusion"))
        return {"status": status, "checks_passed": valid, "results": []}
    if status != "completed":
        return {"status": str(status), "checks_passed": False, "results": []}

    checked: list[dict[str, Any]] = []
    all_valid = True
    for result in evidence.get("results", []):
        derived = _derive_classification(
            float(result["relative_objective_change"]),
            bool(result.get("solution_structure_changed", False)),
            bool(result.get("main_conclusion_reversed", False)),
        )
        valid = result.get("classification") == derived
        all_valid = all_valid and valid
        checked.append({**dict(result), "derived_classification": derived, "classification_valid": valid})
    all_valid = all_valid and bool(checked)
    return {"status": status, "checks_passed": all_valid, "results": checked}

