"""按 artifact_type 与 schema_version 分派路线竞争合同。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "runtime_contracts" / "route_contract_dispatch_v1.json"


class RouteContractError(ValueError):
    """路线合同版本、Schema 或语义不满足注册约束。"""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouteContractError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RouteContractError(f"JSON 顶层必须是对象：{path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dispatch_registry(root: Path = ROOT) -> dict[str, Any]:
    registry_path = root / "runtime_contracts" / "route_contract_dispatch_v1.json"
    registry = _load_object(registry_path)
    schema = _load_object(root / "schemas" / "route_contract_dispatch.schema.json")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(registry),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise RouteContractError(f"路线合同分派注册表不符合 Schema：{errors[0].message}")
    for historical in registry["historical_contracts"]:
        historical_path = root / historical["schema_path"]
        if _sha256(historical_path) != historical["sha256"]:
            raise RouteContractError(f"历史合同哈希漂移：{historical['schema_path']}")
    seen: set[tuple[str, str]] = set()
    for record in registry["artifacts"]:
        key = (record["artifact_type"], record["schema_version"])
        if key in seen:
            raise RouteContractError(f"路线合同分派重复：{key}")
        seen.add(key)
        if not (root / record["schema_path"]).is_file():
            raise RouteContractError(f"注册 Schema 不存在：{record['schema_path']}")
        if record["artifact_type"] != "model_route_v2" and "new_problem" in record["activation_contexts"]:
            raise RouteContractError(f"review_ready 合同不得进入 new_problem：{record['artifact_type']}")
    return registry


def schema_path_for_artifact(
    artifact: Mapping[str, Any], *, context: str, root: Path = ROOT
) -> Path:
    registry = load_dispatch_registry(root)
    artifact_type = artifact.get("artifact_type")
    schema_version = artifact.get("schema_version")
    matches = [
        record
        for record in registry["artifacts"]
        if record["artifact_type"] == artifact_type
        and record["schema_version"] == schema_version
    ]
    if len(matches) != 1:
        raise RouteContractError(
            f"未注册的路线合同：artifact_type={artifact_type!r}, schema_version={schema_version!r}"
        )
    record = matches[0]
    if context not in record["activation_contexts"]:
        raise RouteContractError(f"合同 {artifact_type} 不允许用于 {context}")
    schema_path = root / record["schema_path"]
    if not schema_path.is_file():
        raise RouteContractError(f"注册 Schema 不存在：{record['schema_path']}")
    return schema_path


def validate_artifact(
    artifact: Mapping[str, Any], *, context: str, root: Path = ROOT
) -> None:
    schema_path = schema_path_for_artifact(artifact, context=context, root=root)
    schema = _load_object(schema_path)
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(artifact),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise RouteContractError(f"路线合同不符合 Schema：{location}: {error.message}")
    if artifact.get("artifact_type") == "model_route_v3":
        validate_model_route_v3_semantics(artifact)


def validate_model_route_v3_semantics(artifact: Mapping[str, Any]) -> None:
    subproblem_ids: set[str] = set()
    for subproblem in artifact.get("subproblems", []):
        subproblem_id = str(subproblem["subproblem_id"])
        if subproblem_id in subproblem_ids:
            raise RouteContractError(f"子问题 ID 重复：{subproblem_id}")
        subproblem_ids.add(subproblem_id)

        constraints = subproblem["business_constraints"]
        constraint_ids = [item["constraint_id"] for item in constraints]
        if len(constraint_ids) != len(set(constraint_ids)):
            raise RouteContractError(f"{subproblem_id}: 业务约束 ID 重复")
        hard_constraints = {
            item["constraint_id"] for item in constraints if item["strength"] == "hard"
        }

        routes = subproblem["routes"]
        route_ids = [route["route_id"] for route in routes]
        if len(route_ids) != len(set(route_ids)):
            raise RouteContractError(f"{subproblem_id}: route_id 重复")
        routes_by_role = {route["role"]: route for route in routes}
        for route in routes:
            missing_hard = hard_constraints - set(route["constraint_ids"])
            if missing_hard:
                raise RouteContractError(
                    f"{subproblem_id}/{route['route_id']}: 遗漏硬业务约束 {sorted(missing_hard)}"
                )

        primary = routes_by_role["primary"]
        alternative = routes_by_role["structural_alternative"]
        if primary["structural_family"] == alternative["structural_family"]:
            raise RouteContractError(f"{subproblem_id}: 备选路线与主路线结构族相同")
        difference = subproblem["structural_difference"]
        if difference["primary_route_id"] != primary["route_id"]:
            raise RouteContractError(f"{subproblem_id}: structural_difference 主路线引用错误")
        if difference["alternative_route_id"] != alternative["route_id"]:
            raise RouteContractError(f"{subproblem_id}: structural_difference 备选路线引用错误")


def validate_route_comparison_semantics(
    comparison: Mapping[str, Any], model_route: Mapping[str, Any]
) -> None:
    validate_artifact(model_route, context="full_replay")
    validate_artifact(comparison, context="full_replay")
    if comparison["run_id"] != model_route["run_id"]:
        raise RouteContractError("路线比较与 model_route_v3 的 run_id 不一致")
    subproblem_id = comparison.get("subproblem_id")
    matching = [
        item for item in model_route.get("subproblems", []) if item["subproblem_id"] == subproblem_id
    ]
    if len(matching) != 1:
        raise RouteContractError(f"比较结果引用未知子问题：{subproblem_id}")
    expected_routes = {route["route_id"]: route["role"] for route in matching[0]["routes"]}
    actual_routes = {item["route_id"]: item["role"] for item in comparison["route_results"]}
    if len(actual_routes) != len(comparison["route_results"]) or actual_routes != expected_routes:
        raise RouteContractError("比较结果的三路线身份与 model_route_v3 不一致")
    roles_to_ids = {role: route_id for route_id, role in expected_routes.items()}
    observed_pairs: set[frozenset[str]] = set()
    for pairwise in comparison["pairwise_comparisons"]:
        left = pairwise["left_route_id"]
        right = pairwise["right_route_id"]
        if left not in expected_routes or right not in expected_routes or left == right:
            raise RouteContractError("路线比较引用未知路线或自比较")
        observed_pairs.add(frozenset((left, right)))
    required_pairs = {
        frozenset((roles_to_ids["baseline"], roles_to_ids["primary"])),
        frozenset((roles_to_ids["primary"], roles_to_ids["structural_alternative"])),
    }
    if not required_pairs.issubset(observed_pairs):
        raise RouteContractError("路线比较缺少基线/主路线或主路线/结构备选证据")
    selected = comparison.get("selected_route_id")
    if selected is not None:
        if selected not in actual_routes:
            raise RouteContractError("选中路线不在三路线结果中")
        selected_result = next(
            item for item in comparison["route_results"] if item["route_id"] == selected
        )
        if (
            selected_result["execution_status"] != "completed"
            or not selected_result["feasible"]
            or selected_result["data_leakage_detected"]
            or selected_result["constraint_violations"]
            or selected_result["stability_status"] == "failed"
        ):
            raise RouteContractError("选中路线未完成、不可行、违约、泄漏或稳定性失败")


def validate_operability_report_semantics(
    report: Mapping[str, Any], contract: Mapping[str, Any]
) -> None:
    validate_artifact(contract, context="full_replay")
    validate_artifact(report, context="full_replay")
    if report["run_id"] != contract["run_id"]:
        raise RouteContractError("可执行性报告与合同的 run_id 不一致")
    if report["selected_route_id"] != contract["selected_route_id"]:
        raise RouteContractError("可执行性报告与合同的 selected_route_id 不一致")
    expected = {item["check_id"]: item["strength"] for item in contract["checks"]}
    actual = {item["check_id"]: item for item in report["checks"]}
    if len(actual) != len(report["checks"]) or set(actual) != set(expected):
        raise RouteContractError("可执行性报告检查项与合同不一致")
    for check_id, strength in expected.items():
        if actual[check_id]["strength"] != strength:
            raise RouteContractError(f"可执行性检查强度漂移：{check_id}")
    failed_hard = [
        check_id
        for check_id, strength in expected.items()
        if strength == "hard" and actual[check_id]["status"] != "passed"
    ]
    if failed_hard and report["overall_status"] != "failed":
        raise RouteContractError("硬可执行性检查未通过时 overall_status 必须为 failed")
    if not failed_hard and report["overall_status"] != "passed":
        raise RouteContractError("全部硬可执行性检查通过时 overall_status 必须为 passed")
    if set(report["hard_violations"]) != set(failed_hard):
        raise RouteContractError("hard_violations 必须精确列出未通过的硬检查 ID")


def validate_risk_report_semantics(
    report: Mapping[str, Any], contract: Mapping[str, Any]
) -> None:
    validate_artifact(contract, context="full_replay")
    validate_artifact(report, context="full_replay")
    if report["run_id"] != contract["run_id"]:
        raise RouteContractError("风险报告与合同的 run_id 不一致")
    risks = {item["risk_id"]: item for item in contract["risks"]}
    decisions = {item["risk_id"]: item for item in report["decisions"]}
    if len(decisions) != len(report["decisions"]) or set(decisions) != set(risks):
        raise RouteContractError("风险报告决策项与合同不一致")
    action_rank = {"advisory": 0, "technical_report_only": 1, "block": 2}
    required_overall_rank = 0
    for risk_id, risk in risks.items():
        decision = decisions[risk_id]
        if not decision["triggered"]:
            if decision["action"] != "advisory" or decision["downgraded_from_default"]:
                raise RouteContractError(f"未触发风险不得降级或阻断：{risk_id}")
            continue
        default_action = risk["default_action"]
        action = decision["action"]
        if action_rank[action] < action_rank[default_action]:
            if not decision["downgraded_from_default"]:
                raise RouteContractError(f"风险降级缺少显式标记：{risk_id}")
            if action not in risk["allowed_degradations"]:
                raise RouteContractError(f"风险采用未授权降级：{risk_id}")
        elif decision["downgraded_from_default"]:
            raise RouteContractError(f"风险动作未降级却声明降级：{risk_id}")
        required_overall_rank = max(required_overall_rank, action_rank[action])
    expected_overall = {0: "allow_paper", 1: "technical_report_only", 2: "block"}[
        required_overall_rank
    ]
    if report["overall_action"] != expected_overall:
        raise RouteContractError("风险报告 overall_action 与逐项处置不一致")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--context", choices=("new_problem", "full_replay"), required=True)
    args = parser.parse_args()
    try:
        artifact = _load_object(args.artifact)
        validate_artifact(artifact, context=args.context)
    except RouteContractError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
