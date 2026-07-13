"""2016-C 的预测误差与剩余时间适用性检查。"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def mean_relative_error(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if len(actual) != len(predicted) or not actual:
        return math.inf
    terms = [abs(float(p) - float(a)) / max(abs(float(a)), 1e-12) for a, p in zip(actual, predicted)]
    return sum(terms) / len(terms)


def validate_result(result: Mapping[str, Any], tolerance: float = 1e-6) -> dict[str, Any]:
    """从逐点真值和预测值独立复算 MRE；本题不派生工程最优性。"""

    curves = result.get("curve_checks", [])
    checks: list[dict[str, Any]] = []
    all_valid = bool(curves)
    for curve in curves:
        recomputed = mean_relative_error(curve.get("actual_time", []), curve.get("predicted_time", []))
        reported = float(curve.get("mre_reported", math.nan))
        valid = math.isfinite(recomputed) and abs(recomputed - reported) <= tolerance
        all_valid = all_valid and valid
        checks.append(
            {
                "curve_id": str(curve.get("curve_id")),
                "mre_reported": reported,
                "mre_recomputed": recomputed,
                "difference": abs(recomputed - reported),
                "valid": valid,
            }
        )
    remaining = result.get("remaining_time_predictions", [])
    remaining_valid = bool(remaining) and all(
        math.isfinite(float(item.get("remaining_minutes", math.nan)))
        and float(item.get("remaining_minutes", -1)) >= 0
        for item in remaining
    )
    return {
        "validator": "a092_2016c_prediction_v1",
        "curve_checks": checks,
        "remaining_time_predictions_valid": remaining_valid,
        "engineering_optimization_applicable": False,
        "optimality_claim_allowed": "unverified_candidate",
        "valid": all_valid and remaining_valid,
    }

