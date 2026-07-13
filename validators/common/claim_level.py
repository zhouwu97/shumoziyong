"""根据求解证据派生允许的最优性声明。"""

from __future__ import annotations

from typing import Any, Mapping


def derive_optimality_claim(
    evidence: Mapping[str, Any], *, feasible: bool, objective_consistent: bool
) -> str:
    """仅依据可检查证据返回最高允许等级。"""

    if not feasible or not objective_consistent:
        return "unverified_candidate"
    method = evidence.get("method")
    independent_checks = bool(evidence.get("independent_checks_passed"))
    if not independent_checks:
        return "unverified_candidate"
    if evidence.get("mathematical_proof_verified") is True:
        return "global_optimum_verified"
    if method == "certifying_solver":
        gap = evidence.get("mip_gap")
        limit = evidence.get("mip_gap_tolerance")
        gap_valid = gap is None or (limit is not None and float(gap) <= float(limit))
        if (
            evidence.get("complete_model_submitted") is True
            and evidence.get("valid_termination") is True
            and evidence.get("solver_certificate_verified") is True
            and gap_valid
        ):
            return "solver_certified_optimum"
    if method == "complete_enumeration" and evidence.get("search_space_complete") is True:
        return "best_feasible_in_enumerated_space"
    if method == "heuristic_search":
        return "best_found_in_search"
    if method == "local_solver":
        return "locally_optimal_candidate"
    if evidence.get("improves_baseline") is True:
        return "feasible_improved_solution"
    return "unverified_candidate"


def claim_is_allowed(requested: str, allowed: str) -> bool:
    """检查声明是否与证据类型一致，允许降级为通用弱声明。"""

    if requested == allowed or requested == "unverified_candidate":
        return True
    return requested == "feasible_improved_solution" and allowed != "unverified_candidate"
