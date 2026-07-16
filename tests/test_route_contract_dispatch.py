from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from route_contract_dispatch import (  # noqa: E402
    RouteContractError,
    load_dispatch_registry,
    validate_artifact,
    validate_operability_report_semantics,
    validate_risk_report_semantics,
    validate_route_comparison_semantics,
)
from export_runtime_pack import PROFILE_FILES, RUNTIME_CONTRACTS, resolve_pack_files  # noqa: E402


SHA = "a" * 64


def _route(route_id: str, role: str, family: str) -> dict[str, object]:
    return {
        "route_id": route_id,
        "role": role,
        "name": f"{role} route",
        "structural_family": family,
        "rationale": "该路线用于独立执行和可审计比较。",
        "model": f"{family} model",
        "assumptions": ["输入数据与题面单位保持一致"],
        "decision_variables": [{"name": "x", "definition": "决策数量", "unit": "个", "source": "problem"}],
        "objectives": ["最小化总成本"],
        "constraint_ids": ["BC-CAPACITY", "BC-INTEGER"],
        "data_requirements": ["需求量和单位成本"],
        "algorithm": f"{family} solver",
        "expected_outputs": ["可执行方案和目标值"],
        "validation_requirements": ["逐条回代硬约束"],
        "failure_conditions": ["没有可行解或约束残差超限"],
    }


def _model_route_v3() -> dict[str, object]:
    return {
        "schema_version": "3.0.0",
        "artifact_type": "model_route_v3",
        "run_id": "run-v3-fixture",
        "problem_id": "problem-fixture",
        "profile": "engineering_optimization",
        "runtime_version": "3.0.0-review",
        "runtime_pack_sha256": SHA,
        "lifecycle": "review_ready",
        "subproblems": [
            {
                "subproblem_id": "Q1",
                "task_type": "optimization",
                "inputs": [{"name": "demand", "definition": "需求量", "unit": "个", "source": "problem/data.csv"}],
                "outputs": [{"name": "plan", "definition": "生产计划", "unit": None, "source": None}],
                "mechanism_hypothesis": {
                    "statement": "成本由固定启动成本和单位运输成本共同驱动。",
                    "rationale": "题面同时给出批次和运输费用。",
                    "falsification_checks": ["去掉固定成本后检查方案结构是否发生预期变化"],
                },
                "business_constraints": [
                    {
                        "constraint_id": "BC-CAPACITY",
                        "statement": "每日产量不得超过容量",
                        "strength": "hard",
                        "source_ref": "problem.pdf#capacity",
                        "verification_method": "逐日计算产量减容量",
                    },
                    {
                        "constraint_id": "BC-INTEGER",
                        "statement": "订单批次数必须为整数",
                        "strength": "hard",
                        "source_ref": "problem.pdf#batch",
                        "verification_method": "检查每个批次变量的整数残差",
                    },
                ],
                "routes": [
                    _route("R-BASE", "baseline", "greedy"),
                    _route("R-MAIN", "primary", "mixed_integer_programming"),
                    _route("R-ALT", "structural_alternative", "dynamic_programming"),
                ],
                "structural_difference": {
                    "primary_route_id": "R-MAIN",
                    "alternative_route_id": "R-ALT",
                    "differs_in": ["decision_representation", "algorithm_family"],
                    "explanation": "主路线一次性联合优化，备选路线按阶段状态递推。",
                },
                "comparison_metrics": ["总成本", "硬约束违约数", "运行时间"],
            }
        ],
        "human_decisions_required": ["确认固定成本机制假设"],
    }


def _model_route_v2() -> dict[str, object]:
    named = [{"name": "x", "definition": "决策量", "unit": None, "source": None}]
    model = {"name": "linear baseline", "rationale": "用于验证历史 v2 合同仍可正常分派。", "implementation_notes": []}
    return {
        "schema_version": "2.0.0",
        "artifact_type": "model_route_v2",
        "run_id": "historical-v2-fixture",
        "problem_id": "problem-fixture",
        "profile": "engineering_optimization",
        "runtime_version": "2.1.0",
        "runtime_pack_sha256": SHA,
        "subproblems": [
            {
                "subproblem_id": "Q1",
                "task_type": "optimization",
                "inputs": named,
                "outputs": named,
                "variables": named,
                "parameters": named,
                "objectives": ["最小化成本"],
                "constraints": ["容量约束"],
                "assumptions": ["输入数据有效"],
                "baseline_model": model,
                "selected_model": model,
                "alternatives_rejected": [],
                "validation_requirements": ["约束回代"],
                "uncertainty_plan": ["参数扰动"],
                "failure_conditions": ["无可行解"],
            }
        ],
        "human_decisions_required": ["确认路线"],
    }


def _route_result(route_id: str, role: str, feasible: bool = True) -> dict[str, object]:
    return {
        "route_id": route_id,
        "role": role,
        "formal_result": {"path": f"formal/{route_id}.json", "sha256": SHA},
        "execution_status": "completed",
        "feasible": feasible,
        "data_leakage_detected": False,
        "metrics": [
            {
                "name": "total_cost",
                "value": 100.0,
                "unit": "CNY",
                "direction": "minimize",
                "evidence": {"path": f"formal/{route_id}.json", "sha256": SHA},
            }
        ],
        "constraint_violations": [] if feasible else ["BC-CAPACITY"],
        "runtime_seconds": 1.0,
        "stability_status": "passed",
    }


def _comparison() -> dict[str, object]:
    pair = {
        "metric_deltas": [{"metric": "total_cost", "left_value": 100.0, "right_value": 90.0, "delta": -10.0}],
        "conclusion": "右侧路线在保持可行时成本更低。",
        "evidence_refs": [{"path": "comparison/metrics.json", "sha256": SHA}],
    }
    return {
        "schema_version": "1.0.0",
        "artifact_type": "route_comparison_result_v1",
        "run_id": "run-v3-fixture",
        "subproblem_id": "Q1",
        "model_route_v3_sha256": SHA,
        "route_results": [
            _route_result("R-BASE", "baseline"),
            _route_result("R-MAIN", "primary"),
            _route_result("R-ALT", "structural_alternative"),
        ],
        "pairwise_comparisons": [
            {"left_route_id": "R-BASE", "right_route_id": "R-MAIN", **pair},
            {"left_route_id": "R-MAIN", "right_route_id": "R-ALT", **pair},
        ],
        "selection_status": "selected",
        "selected_route_id": "R-MAIN",
        "selection_basis": "主路线可行且在成本与稳定性证据上优于基线。",
        "formal_result_authority": "collector_and_independent_validator_required",
    }


def _operability_contract() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "operability_contract_v1",
        "run_id": "run-v3-fixture",
        "subproblem_id": "Q1",
        "model_route_v3_sha256": SHA,
        "selected_route_id": "R-MAIN",
        "fail_closed": True,
        "repair_revalidation_required": True,
        "checks": [
            {
                "check_id": "OP-INTEGER",
                "category": "integrality",
                "strength": "hard",
                "statement": "批次数必须为整数",
                "measurement": "最大整数残差",
                "acceptance_rule": "残差等于零",
                "source_ref": "BC-INTEGER",
            }
        ],
    }


def _operability_report() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "operability_report_v1",
        "run_id": "run-v3-fixture",
        "operability_contract_sha256": SHA,
        "formal_result_sha256": SHA,
        "selected_route_id": "R-MAIN",
        "checks": [
            {
                "check_id": "OP-INTEGER",
                "strength": "hard",
                "status": "passed",
                "observed": "最大整数残差为 0",
                "evidence_refs": [{"path": "formal/checks.json", "sha256": SHA}],
            }
        ],
        "overall_status": "passed",
        "hard_violations": [],
        "validator": {"validator_id": "independent-operability-v1", "independent_from_executor": True},
    }


def _risk_contract() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "risk_decision_contract_v1",
        "run_id": "run-v3-fixture",
        "subproblem_id": "Q1",
        "model_route_v3_sha256": SHA,
        "unexplained_downgrade_forbidden": True,
        "risks": [
            {
                "risk_id": "RISK-INFEASIBLE",
                "category": "feasibility",
                "trigger": "任一硬约束检查未通过",
                "severity": "fatal",
                "default_action": "block",
                "allowed_degradations": ["technical_report_only"],
                "evidence_required": ["可执行性独立报告"],
            }
        ],
    }


def _risk_report() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "risk_decision_report_v1",
        "run_id": "run-v3-fixture",
        "risk_decision_contract_sha256": SHA,
        "formal_result_sha256": SHA,
        "decisions": [
            {
                "risk_id": "RISK-INFEASIBLE",
                "triggered": False,
                "action": "advisory",
                "rationale": "全部硬约束检查均已通过。",
                "evidence_refs": [{"path": "reports/operability.json", "sha256": SHA}],
                "downgraded_from_default": False,
            }
        ],
        "overall_action": "allow_paper",
        "validator": {"validator_id": "independent-risk-v1", "independent_from_executor": True},
    }


def test_dispatch_keeps_v2_immutable_and_v3_full_replay_only() -> None:
    registry = load_dispatch_registry()
    historical = registry["historical_contracts"][0]
    actual_hash = hashlib.sha256((ROOT / historical["schema_path"]).read_bytes()).hexdigest()
    assert actual_hash == historical["sha256"]

    validate_artifact(_model_route_v2(), context="new_problem")

    validate_artifact(_model_route_v3(), context="full_replay")
    with pytest.raises(RouteContractError, match="不允许用于 new_problem"):
        validate_artifact(_model_route_v3(), context="new_problem")


def test_v3_contracts_compile_only_into_review_ready_full_replay_packs() -> None:
    compiled_paths = {
        "runtime_contracts/route_contract_dispatch_v1.json",
        "schemas/model_route_v3.schema.json",
        "schemas/route_comparison_result.schema.json",
        "schemas/operability_contract.schema.json",
        "schemas/operability_report.schema.json",
        "schemas/risk_decision_contract.schema.json",
        "schemas/risk_decision_report.schema.json",
        "schemas/route_execution_report.schema.json",
        "schemas/competition_gate3_decision.schema.json",
        "runtime_contracts/score_v3_policy_v1.json",
        "schemas/score_v3_ratings.schema.json",
        "schemas/score_v3.schema.json",
    }
    for profile in PROFILE_FILES:
        for workflow_context in RUNTIME_CONTRACTS:
            files = set(resolve_pack_files(profile, workflow_context))
            should_activate = workflow_context == "full_replay" and profile in {
                "general",
                "engineering_optimization",
                "evaluation",
                "prediction",
            }
            if should_activate:
                assert compiled_paths.issubset(files)
            else:
                assert files.isdisjoint(compiled_paths)


def test_v3_requires_three_roles_and_structurally_different_alternative() -> None:
    route = _model_route_v3()
    subproblem = route["subproblems"][0]
    assert isinstance(subproblem, dict)
    routes = subproblem["routes"]
    assert isinstance(routes, list)
    routes.pop()
    with pytest.raises(RouteContractError, match="不符合 Schema"):
        validate_artifact(route, context="full_replay")

    route = _model_route_v3()
    subproblem = route["subproblems"][0]
    assert isinstance(subproblem, dict)
    routes = subproblem["routes"]
    assert isinstance(routes, list)
    primary = next(item for item in routes if item["role"] == "primary")
    alternative = next(item for item in routes if item["role"] == "structural_alternative")
    alternative["structural_family"] = primary["structural_family"]
    with pytest.raises(RouteContractError, match="结构族相同"):
        validate_artifact(route, context="full_replay")


def test_v3_rejects_omitted_hard_business_constraint() -> None:
    route = _model_route_v3()
    subproblem = route["subproblems"][0]
    assert isinstance(subproblem, dict)
    routes = subproblem["routes"]
    assert isinstance(routes, list)
    routes[0]["constraint_ids"] = ["BC-CAPACITY"]

    with pytest.raises(RouteContractError, match="遗漏硬业务约束"):
        validate_artifact(route, context="full_replay")


def test_comparison_requires_matching_three_route_results_and_feasible_selection() -> None:
    route = _model_route_v3()
    comparison = _comparison()
    validate_route_comparison_semantics(comparison, route)

    incomplete = copy.deepcopy(comparison)
    pairwise = incomplete["pairwise_comparisons"]
    assert isinstance(pairwise, list)
    pairwise[1]["left_route_id"] = "R-BASE"
    with pytest.raises(RouteContractError, match="路线比较缺少"):
        validate_route_comparison_semantics(incomplete, route)

    route_results = comparison["route_results"]
    assert isinstance(route_results, list)
    selected = next(item for item in route_results if item["route_id"] == "R-MAIN")
    selected["feasible"] = False
    selected["constraint_violations"] = ["BC-CAPACITY"]
    with pytest.raises(RouteContractError, match="选中路线未完成"):
        validate_route_comparison_semantics(comparison, route)

    comparison = _comparison()
    comparison["run_id"] = "another-run"
    with pytest.raises(RouteContractError, match="run_id 不一致"):
        validate_route_comparison_semantics(comparison, route)


def test_operability_report_is_fail_closed_for_hard_checks() -> None:
    contract = _operability_contract()
    report = _operability_report()
    validate_artifact(contract, context="full_replay")
    validate_operability_report_semantics(report, contract)

    checks = report["checks"]
    assert isinstance(checks, list)
    checks[0]["status"] = "not_evaluated"
    report["hard_violations"] = ["OP-INTEGER"]
    with pytest.raises(RouteContractError, match="overall_status 必须为 failed"):
        validate_operability_report_semantics(report, contract)

    report = _operability_report()
    report["selected_route_id"] = "R-ALT"
    with pytest.raises(RouteContractError, match="selected_route_id 不一致"):
        validate_operability_report_semantics(report, contract)


def test_risk_downgrade_requires_reason_and_authorized_action() -> None:
    contract = _risk_contract()
    report = _risk_report()
    validate_artifact(contract, context="full_replay")
    validate_risk_report_semantics(report, contract)

    decision = report["decisions"][0]
    assert isinstance(decision, dict)
    decision.update(
        {
            "triggered": True,
            "action": "technical_report_only",
            "downgraded_from_default": True,
            "downgrade_reason": "已有独立证据证明结果仍可作为技术报告使用。",
        }
    )
    report["overall_action"] = "technical_report_only"
    validate_risk_report_semantics(report, contract)

    decision["action"] = "advisory"
    with pytest.raises(RouteContractError, match="未授权降级"):
        validate_risk_report_semantics(report, contract)

    report = _risk_report()
    decision = report["decisions"][0]
    assert isinstance(decision, dict)
    decision["action"] = "block"
    with pytest.raises(RouteContractError, match="未触发风险不得"):
        validate_risk_report_semantics(report, contract)
