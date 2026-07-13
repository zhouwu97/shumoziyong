"""A092 Validator v0 的组合入口。"""

from __future__ import annotations

from typing import Any, Mapping

from .claim_level import claim_is_allowed, derive_optimality_claim
from .improvement import compare_with_baseline
from .residuals import check_constraints, check_integrality, check_variable_bounds
from .sensitivity import run_sensitivity_checks
from .types import ProblemAdapter


def recompute_objective(
    adapter: ProblemAdapter,
    solution: Mapping[str, float],
    problem_data: Mapping[str, Any],
) -> float:
    """调用题目固定评价器复算目标值。"""

    return float(adapter.evaluate_solution(solution, problem_data))


def validate_solution(
    adapter: ProblemAdapter,
    *,
    solution: Mapping[str, float],
    problem_data: Mapping[str, Any],
    objective_reported: float,
    baseline_solution: Mapping[str, float],
    reported_improvement_ratio: float | None,
    sensitivity_evidence: Mapping[str, Any],
    optimality_evidence: Mapping[str, Any],
    requested_optimality_claim: str,
    tolerances: Mapping[str, float],
) -> dict[str, Any]:
    """执行目标、域、约束、改进率、敏感性和最优性联合验证。"""

    objective_recomputed = recompute_objective(adapter, solution, problem_data)
    objective_difference = abs(float(objective_reported) - objective_recomputed)
    objective_consistent = objective_difference <= float(tolerances["objective_absolute"])
    bounds_valid, bound_violations = check_variable_bounds(
        solution,
        adapter.variable_specs,
        absolute_tolerance=float(tolerances["variable_absolute"]),
    )
    integrality_valid, integrality_violations = check_integrality(
        solution,
        adapter.variable_specs,
        integrality_tolerance=float(tolerances["integrality_absolute"]),
    )
    constraint_results, violated_constraints, max_raw, max_scaled = check_constraints(
        adapter.evaluate_constraints(solution, problem_data),
        absolute_tolerance=float(tolerances["constraint_absolute"]),
        relative_tolerance=float(tolerances["constraint_relative"]),
    )
    baseline_objective = recompute_objective(adapter, baseline_solution, problem_data)
    comparison = compare_with_baseline(
        objective_direction=adapter.objective_direction,
        baseline_objective=baseline_objective,
        candidate_objective=objective_recomputed,
        epsilon=float(tolerances["baseline_epsilon"]),
        reported_ratio=reported_improvement_ratio,
        ratio_tolerance=float(tolerances["improvement_ratio_absolute"]),
    )
    sensitivity = run_sensitivity_checks(sensitivity_evidence)
    feasible = bounds_valid and integrality_valid and not violated_constraints
    allowed_claim = derive_optimality_claim(
        optimality_evidence,
        feasible=feasible,
        objective_consistent=objective_consistent,
    )
    claim_consistent = claim_is_allowed(requested_optimality_claim, allowed_claim)
    valid = all(
        [
            objective_consistent,
            feasible,
            bool(comparison["improvement_ratio_consistent"]),
            bool(sensitivity["checks_passed"]),
            claim_consistent,
        ]
    )
    return {
        "schema_version": "1.0.0",
        "validator": "a092_validator_v0",
        "objective_direction": adapter.objective_direction,
        "feasible": feasible,
        "objective_reported": float(objective_reported),
        "objective_recomputed": objective_recomputed,
        "objective_difference": objective_difference,
        "objective_consistent": objective_consistent,
        "max_raw_constraint_violation": max_raw,
        "max_scaled_constraint_violation": max_scaled,
        "violated_constraints": violated_constraints,
        "constraint_results": constraint_results,
        "baseline_objective": baseline_objective,
        "absolute_improvement": comparison["absolute_improvement"],
        "improvement_ratio": comparison["improvement_ratio"],
        "improvement_ratio_reported": reported_improvement_ratio,
        "improvement_ratio_consistent": comparison["improvement_ratio_consistent"],
        "baseline_near_zero": comparison["baseline_near_zero"],
        "bounds_valid": bounds_valid,
        "bound_violations": bound_violations,
        "integrality_valid": integrality_valid,
        "integrality_violations": integrality_violations,
        "sensitivity_status": sensitivity["status"],
        "sensitivity_checks_passed": sensitivity["checks_passed"],
        "sensitivity_results": sensitivity["results"],
        "optimality_claim_requested": requested_optimality_claim,
        "optimality_claim_allowed": allowed_claim,
        "optimality_claim_consistent": claim_consistent,
        "global_optimality_verified": allowed_claim == "global_optimum_verified",
        "valid": valid,
    }

