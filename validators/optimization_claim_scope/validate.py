"""依据决策空间和求解状态约束优化结论的允许措辞。"""

from __future__ import annotations

from typing import Any, Mapping


ALLOWED_CONCLUSIONS = {
    "global_optimum",
    "candidate_set_optimum",
    "best_known_heuristic",
    "feasible_not_proven_optimal",
    "local_infeasible",
    "globally_infeasible",
    "no_feasible_solution_found_within_limit",
    "unable_to_determine",
}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _covers_complete_decision_space(audit: Mapping[str, Any]) -> tuple[bool, str]:
    decision_space = audit.get("decision_space", {})
    original_count = _positive_int(decision_space.get("original_candidate_count"))
    modeled_count = _positive_int(decision_space.get("modeled_candidate_count"))
    safety_proven = decision_space.get("candidate_reduction_safety_proven") is True

    if original_count is None or modeled_count is None:
        return False, "缺少可核验的原题候选数量或正式模型候选数量。"
    if modeled_count > original_count:
        return False, "正式模型候选数量大于原题候选数量，审计输入不一致。"
    if modeled_count == original_count:
        return True, "正式模型覆盖原题全部候选对象。"
    if safety_proven:
        return True, "候选集合虽有缩减，但已声明存在严格安全证明。"
    return False, "正式模型截断了候选集合，且没有严格安全证明。"


def assess_claim_scope(audit: Mapping[str, Any]) -> dict[str, Any]:
    """返回当前证据允许的唯一结论及必须禁止的越界结论。"""
    solver = audit.get("solver", {})
    scope = str(audit.get("problem_scope", "")).strip()
    status = str(solver.get("status", "")).strip().lower()
    has_incumbent = solver.get("has_incumbent") is True
    has_infeasibility_certificate = solver.get("has_infeasibility_certificate") is True
    full_space, space_reason = _covers_complete_decision_space(audit)

    result = "unable_to_determine"
    reasons = [space_reason]

    if status in {"optimal", "globally_optimal"}:
        preserves_prior_optima = audit.get("lexicographic", {}).get(
            "preserves_all_prior_optima"
        )
        if preserves_prior_optima is False:
            result = "candidate_set_optimum"
            reasons.append("后续阶段固定了前序具体解，未保留前序最优集合中的全部可能解。")
        elif full_space and scope == "complete_model":
            result = "global_optimum"
            reasons.append("求解器报告最优，且审计范围覆盖完整决策空间。")
        else:
            result = "candidate_set_optimum"
            reasons.append("最优性证据仅覆盖被审计的受限候选空间。")
    elif status == "infeasible":
        if full_space and scope == "complete_model" and has_infeasibility_certificate:
            result = "globally_infeasible"
            reasons.append("完整模型具有不可行证书。")
        else:
            result = "local_infeasible"
            reasons.append("不可行结果未同时覆盖完整模型、完整决策空间和不可行证书。")
    elif status in {"time_limit", "limit_reached"} and not has_incumbent:
        result = "no_feasible_solution_found_within_limit"
        reasons.append("求解在限制内结束，且没有可行 incumbent。")
    elif has_incumbent:
        if scope == "heuristic_search_space" or status in {"heuristic", "best_known"}:
            result = "best_known_heuristic"
            reasons.append("当前证据来自启发式搜索空间，不能证明最优。")
        else:
            result = "feasible_not_proven_optimal"
            reasons.append("已有可行解，但求解状态没有证明最优。")
    else:
        reasons.append("求解状态与可行性证据不足以形成更强结论。")

    forbidden = sorted(ALLOWED_CONCLUSIONS - {result, "unable_to_determine"})
    return {
        "allowed_conclusion": result,
        "forbidden_conclusions": forbidden,
        "decision_space_complete": full_space,
        "reasons": reasons,
    }
