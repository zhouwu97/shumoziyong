from __future__ import annotations

from validators.optimization_claim_scope import assess_claim_scope


def test_unsafe_candidate_truncation_is_only_candidate_set_optimum() -> None:
    """能力前 K 家被预先固定时，成本最优性不得扩展到完整候选空间。"""
    audit = {
        "decision_space": {
            "original_candidate_count": 6,
            "modeled_candidate_count": 3,
            "candidate_set_fixed_before_optimization": True,
            "candidate_reduction_safety_proven": False,
        },
        "lexicographic": {"preserves_all_prior_optima": False},
        "solver": {
            "status": "optimal",
            "has_incumbent": True,
            "has_infeasibility_certificate": False,
        },
        "problem_scope": "fixed_candidate_set",
    }

    report = assess_claim_scope(audit)

    assert report["allowed_conclusion"] == "candidate_set_optimum"
    assert "global_optimum" in report["forbidden_conclusions"]


def test_local_infeasible_does_not_imply_global_infeasible() -> None:
    """固定候选集不可行但加入未入选对象可行时，只允许局部不可行结论。"""
    audit = {
        "decision_space": {
            "original_candidate_count": 4,
            "modeled_candidate_count": 3,
            "candidate_set_fixed_before_optimization": True,
            "candidate_reduction_safety_proven": False,
        },
        "lexicographic": {"preserves_all_prior_optima": True},
        "solver": {
            "status": "infeasible",
            "has_incumbent": False,
            "has_infeasibility_certificate": True,
        },
        "problem_scope": "fixed_candidate_set",
    }

    report = assess_claim_scope(audit)

    assert report["allowed_conclusion"] == "local_infeasible"
    assert "globally_infeasible" in report["forbidden_conclusions"]
