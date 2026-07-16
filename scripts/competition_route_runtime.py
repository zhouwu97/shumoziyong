"""三路线独立执行与 Gate 3 证据汇总，不替代 Collector 或 Formal Result。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from executor_core import execute_spec
from formal_result.identity import IMMUTABLE_IDENTITY_FIELDS
from formal_result.path_safety import (
    validate_execution_command_bindings,
    validate_execution_spec_paths,
)
from formal_result.verifier import verify_formal_result_bundle
from route_contract_dispatch import (
    RouteContractError,
    validate_artifact,
    validate_operability_report_semantics,
    validate_risk_report_semantics,
    validate_route_comparison_semantics,
)


ROOT = Path(__file__).resolve().parents[1]
RUN_IDENTITY_FIELDS = (
    "problem_id",
    "profile",
    "runtime_version",
    "runtime_pack_sha256",
)
EVIDENCE_FILENAMES = {
    "model_route": "model_route_v3.json",
    "execution": "route_execution_report_{subproblem_id}.json",
    "comparison": "route_comparison_result_{subproblem_id}.json",
    "operability_contract": "operability_contract_{subproblem_id}.json",
    "operability_report": "operability_report_{subproblem_id}.json",
    "risk_contract": "risk_decision_contract_{subproblem_id}.json",
    "risk_report": "risk_decision_report_{subproblem_id}.json",
    "decision": "competition_gate3_decision_{subproblem_id}.json",
}


class CompetitionRouteRuntimeError(ValueError):
    """三路线运行目录、身份或证据闭包不满足要求。"""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompetitionRouteRuntimeError(f"{label} 无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise CompetitionRouteRuntimeError(f"{label} 顶层必须是对象")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _validate_schema(value: Mapping[str, Any], schema_name: str, label: str) -> None:
    schema = _load_object(ROOT / "schemas" / schema_name, schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise CompetitionRouteRuntimeError(
            f"{label} 不符合 Schema：{location}: {error.message}"
        )


def _safe_relative(root: Path, relative: str, label: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
        raise CompetitionRouteRuntimeError(f"{label} 必须是安全相对路径")
    candidate = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CompetitionRouteRuntimeError(f"{label} 禁止符号链接：{relative}")
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise CompetitionRouteRuntimeError(f"{label} 越出父 Run") from exc
    return candidate


def _subproblem(model_route: Mapping[str, Any], subproblem_id: str) -> Mapping[str, Any]:
    matches = [
        item
        for item in model_route["subproblems"]
        if item["subproblem_id"] == subproblem_id
    ]
    if len(matches) != 1:
        raise CompetitionRouteRuntimeError(f"model_route_v3 不含唯一子问题：{subproblem_id}")
    return matches[0]


def _validate_parent_identity(
    parent_root: Path, model_route: Mapping[str, Any]
) -> dict[str, Any]:
    manifest = _load_object(parent_root / "run_manifest.json", "父 run_manifest.json")
    for field in ("run_id", *RUN_IDENTITY_FIELDS):
        if manifest.get(field) != model_route.get(field):
            raise CompetitionRouteRuntimeError(
                f"父 run_manifest.{field} 与 model_route_v3 不一致"
            )
    return manifest


def _child_relative(subproblem_id: str, route_id: str) -> str:
    return f"route_runs/{subproblem_id}/{route_id}"


def _preflight_child(
    parent_root: Path,
    model_route: Mapping[str, Any],
    subproblem_id: str,
    route: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    relative = _child_relative(subproblem_id, str(route["route_id"]))
    child_root = _safe_relative(parent_root, relative, f"路线 {route['route_id']} 子 Run")
    if not child_root.is_dir():
        raise CompetitionRouteRuntimeError(f"缺少路线子 Run：{relative}")
    manifest = _load_object(child_root / "run_manifest.json", f"{relative}/run_manifest.json")
    spec = _load_object(child_root / "execution_spec.json", f"{relative}/execution_spec.json")
    _validate_schema(spec, "execution_spec.schema.json", f"{relative}/execution_spec.json")
    try:
        validate_execution_spec_paths(spec)
        validate_execution_command_bindings(spec, child_root)
    except ValueError as exc:
        raise CompetitionRouteRuntimeError(f"{relative}/execution_spec 路径合同无效：{exc}") from exc
    for field in RUN_IDENTITY_FIELDS:
        if manifest.get(field) != model_route.get(field):
            raise CompetitionRouteRuntimeError(
                f"{relative}/run_manifest.{field} 与 model_route_v3 不一致"
            )
    for field in IMMUTABLE_IDENTITY_FIELDS:
        if spec.get(field) != manifest.get(field):
            raise CompetitionRouteRuntimeError(
                f"{relative}/execution_spec.{field} 与子 Run 不一致"
            )
    workspace = child_root.joinpath(*PurePosixPath(spec["declared_workspace"]).parts)
    for task in spec["tasks"]:
        entrypoint = workspace.joinpath(*PurePosixPath(task["entrypoint"]).parts)
        if not entrypoint.is_file():
            raise CompetitionRouteRuntimeError(
                f"{relative}/execution_spec 缺少批准入口：{task['entrypoint']}"
            )
        for item in task["inputs"]:
            input_path = child_root.joinpath(*PurePosixPath(item["path"]).parts)
            if not input_path.is_file() or _sha256(input_path) != item["sha256"]:
                raise CompetitionRouteRuntimeError(
                    f"{relative}/execution_spec 输入缺失或哈希漂移：{item['path']}"
                )
    return child_root, manifest, spec


def execute_three_routes(
    parent_run_dir: Path,
    subproblem_id: str,
    executor_id: str,
) -> dict[str, Any]:
    """预检三个隔离子 Run 后逐一调用现有 Executor，任何路线都不会被省略。"""
    parent_root = parent_run_dir.resolve()
    model_path = parent_root / EVIDENCE_FILENAMES["model_route"]
    model_route = _load_object(model_path, "model_route_v3.json")
    validate_artifact(model_route, context="full_replay")
    _validate_parent_identity(parent_root, model_route)
    subproblem = _subproblem(model_route, subproblem_id)

    prepared: list[tuple[Mapping[str, Any], Path, dict[str, Any]]] = []
    child_run_ids: set[str] = set()
    for route in subproblem["routes"]:
        child_root, manifest, _spec = _preflight_child(
            parent_root, model_route, subproblem_id, route
        )
        child_run_id = str(manifest.get("run_id", ""))
        if not child_run_id or child_run_id in child_run_ids:
            raise CompetitionRouteRuntimeError("三路线必须绑定三个不同的非空 child_run_id")
        child_run_ids.add(child_run_id)
        prepared.append((route, child_root, manifest))

    routes: list[dict[str, Any]] = []
    for route, child_root, manifest in prepared:
        record = execute_spec(child_root / "execution_spec.json", child_root, executor_id)
        spec_path = child_root / "execution_spec.json"
        record_path = child_root / "candidate_execution_record.json"
        child_relative = child_root.relative_to(parent_root).as_posix()
        routes.append(
            {
                "route_id": route["route_id"],
                "role": route["role"],
                "child_run_id": manifest["run_id"],
                "child_root": child_relative,
                "execution_spec": {
                    "path": f"{child_relative}/execution_spec.json",
                    "sha256": _sha256(spec_path),
                },
                "candidate_execution_record": {
                    "path": f"{child_relative}/candidate_execution_record.json",
                    "sha256": _sha256(record_path),
                },
                "execution_status": record["status"],
                "blocker_ref": record["blocker_ref"],
            }
        )

    report = {
        "schema_version": "1.0.0",
        "artifact_type": "route_execution_report_v1",
        "run_id": model_route["run_id"],
        "subproblem_id": subproblem_id,
        "model_route_v3_sha256": _sha256(model_path),
        "executor_id": executor_id,
        "all_routes_attempted": True,
        "status": (
            "completed"
            if all(item["execution_status"] == "completed" for item in routes)
            else "blocked"
        ),
        "routes": routes,
    }
    validate_artifact(report, context="full_replay")
    output_path = parent_root / EVIDENCE_FILENAMES["execution"].format(
        subproblem_id=subproblem_id
    )
    _write_json_atomic(output_path, report)
    return report


def _validate_execution_report(
    parent_root: Path,
    report: Mapping[str, Any],
    model_route: Mapping[str, Any],
    subproblem: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    validate_artifact(report, context="full_replay")
    if report["run_id"] != model_route["run_id"]:
        raise CompetitionRouteRuntimeError("route_execution_report.run_id 不一致")
    if report["subproblem_id"] != subproblem["subproblem_id"]:
        raise CompetitionRouteRuntimeError("route_execution_report.subproblem_id 不一致")
    expected = {route["route_id"]: route for route in subproblem["routes"]}
    actual = {item["route_id"]: item for item in report["routes"]}
    if len(actual) != len(report["routes"]) or set(actual) != set(expected):
        raise CompetitionRouteRuntimeError("执行报告未精确覆盖三条路线")
    roots: set[str] = set()
    child_run_ids: set[str] = set()
    for route_id, route in expected.items():
        item = actual[route_id]
        expected_root = _child_relative(str(subproblem["subproblem_id"]), route_id)
        if item["role"] != route["role"] or item["child_root"] != expected_root:
            raise CompetitionRouteRuntimeError(f"执行报告路线身份或子目录错误：{route_id}")
        if item["child_root"] in roots or item["child_run_id"] in child_run_ids:
            raise CompetitionRouteRuntimeError("三路线不得复用 child_root 或 child_run_id")
        roots.add(item["child_root"])
        child_run_ids.add(item["child_run_id"])
        child_root, manifest, _spec = _preflight_child(
            parent_root,
            model_route,
            str(subproblem["subproblem_id"]),
            route,
        )
        if manifest.get("run_id") != item["child_run_id"]:
            raise CompetitionRouteRuntimeError(f"执行报告 child_run_id 漂移：{route_id}")
        for ref_name in ("execution_spec", "candidate_execution_record"):
            ref = item[ref_name]
            path = _safe_relative(parent_root, ref["path"], f"{route_id}/{ref_name}")
            if not path.is_file() or _sha256(path) != ref["sha256"]:
                raise CompetitionRouteRuntimeError(f"执行报告文件引用漂移：{route_id}/{ref_name}")
        record = _load_object(
            child_root / "candidate_execution_record.json", f"{route_id}/candidate_execution_record"
        )
        _validate_schema(record, "execution_record.schema.json", f"{route_id}/candidate_execution_record")
        if (
            record["run_id"] != item["child_run_id"]
            or record["status"] != item["execution_status"]
            or record["executor_id"] != report["executor_id"]
            or record["execution_spec_sha256"] != item["execution_spec"]["sha256"]
            or record["blocker_ref"] != item["blocker_ref"]
        ):
            raise CompetitionRouteRuntimeError(f"执行报告与候选执行记录不一致：{route_id}")
    expected_status = (
        "completed"
        if all(item["execution_status"] == "completed" for item in report["routes"])
        else "blocked"
    )
    if report["status"] != expected_status:
        raise CompetitionRouteRuntimeError("执行报告顶层 status 与三条路线记录不一致")
    return actual


def _load_gate3_evidence(parent_root: Path, subproblem_id: str) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for key, template in EVIDENCE_FILENAMES.items():
        if key == "decision":
            continue
        path = parent_root / template.format(subproblem_id=subproblem_id)
        evidence[key] = _load_object(path, path.name)
    return evidence


def evaluate_competition_gate3(
    parent_run_dir: Path,
    subproblem_id: str,
    validator_id: str,
    *,
    write_report: bool = True,
) -> dict[str, Any]:
    """绑定三条 Formal Result、比较、可执行性与风险证据并生成 Gate 3 决策。"""
    parent_root = parent_run_dir.resolve()
    evidence = _load_gate3_evidence(parent_root, subproblem_id)
    model_route = evidence["model_route"]
    validate_artifact(model_route, context="full_replay")
    _validate_parent_identity(parent_root, model_route)
    subproblem = _subproblem(model_route, subproblem_id)
    model_path = parent_root / EVIDENCE_FILENAMES["model_route"]
    model_sha = _sha256(model_path)

    execution_report = evidence["execution"]
    execution_routes = _validate_execution_report(
        parent_root, execution_report, model_route, subproblem
    )
    if execution_report["model_route_v3_sha256"] != model_sha:
        raise CompetitionRouteRuntimeError("执行报告未绑定当前 model_route_v3")

    comparison = evidence["comparison"]
    comparison_error: RouteContractError | None = None
    try:
        validate_route_comparison_semantics(comparison, model_route)
    except RouteContractError as exc:
        if "选中路线未完成、不可行、违约、泄漏或稳定性失败" not in str(exc):
            raise
        comparison_error = exc
    if comparison["model_route_v3_sha256"] != model_sha:
        raise CompetitionRouteRuntimeError("路线比较未绑定当前 model_route_v3")

    route_results = {item["route_id"]: item for item in comparison["route_results"]}
    formal_results: list[dict[str, Any]] = []
    formal_by_route: dict[str, dict[str, Any]] = {}
    for route in subproblem["routes"]:
        route_id = route["route_id"]
        execution = execution_routes[route_id]
        child_root = _safe_relative(parent_root, execution["child_root"], f"{route_id} 子 Run")
        envelopes = sorted(child_root.glob("formal_results/*/formal_result_envelope.json"))
        if len(envelopes) != 1:
            raise CompetitionRouteRuntimeError(
                f"路线 {route_id} 必须且只能包含一个 Formal Result Envelope，实际 {len(envelopes)}"
            )
        summary = verify_formal_result_bundle(child_root, envelopes[0])
        if summary["identity"]["run_id"] != execution["child_run_id"]:
            raise CompetitionRouteRuntimeError(f"路线 {route_id} Formal Result 与 child_run_id 不一致")
        envelope_parent_relative = envelopes[0].relative_to(parent_root).as_posix()
        envelope_sha = _sha256(envelopes[0])
        comparison_ref = route_results[route_id]["formal_result"]
        if comparison_ref != {"path": envelope_parent_relative, "sha256": envelope_sha}:
            raise CompetitionRouteRuntimeError(f"路线比较未精确绑定 {route_id} Formal Result")
        item = {
            "route_id": route_id,
            "role": route["role"],
            "child_run_id": execution["child_run_id"],
            "envelope_path": envelope_parent_relative,
            "envelope_sha256": envelope_sha,
            "formal_result_id": summary["formal_result_id"],
            "formal_result_eligible": bool(summary["formal_result_eligible"]),
        }
        formal_results.append(item)
        formal_by_route[route_id] = item

    operability_contract = evidence["operability_contract"]
    operability_report = evidence["operability_report"]
    validate_operability_report_semantics(operability_report, operability_contract)
    risk_contract = evidence["risk_contract"]
    risk_report = evidence["risk_report"]
    validate_risk_report_semantics(risk_report, risk_contract)
    for contract_name, contract in (
        ("operability_contract", operability_contract),
        ("risk_contract", risk_contract),
    ):
        if (
            contract["run_id"] != model_route["run_id"]
            or contract["subproblem_id"] != subproblem_id
            or contract["model_route_v3_sha256"] != model_sha
        ):
            raise CompetitionRouteRuntimeError(f"{contract_name} 未绑定当前 Run、子问题或模型路线")

    selected_route_id = comparison.get("selected_route_id")
    if not isinstance(selected_route_id, str) or selected_route_id not in formal_by_route:
        raise CompetitionRouteRuntimeError("Gate 3 完整证据必须选择一条已验证路线")
    selected_formal_sha = formal_by_route[selected_route_id]["envelope_sha256"]
    if operability_contract["selected_route_id"] != selected_route_id:
        raise CompetitionRouteRuntimeError("可执行性合同未绑定比较结果选中路线")

    artifact_paths = {
        key: parent_root / EVIDENCE_FILENAMES[key].format(subproblem_id=subproblem_id)
        for key in (
            "execution",
            "comparison",
            "operability_contract",
            "operability_report",
            "risk_contract",
            "risk_report",
        )
    }
    if operability_report["operability_contract_sha256"] != _sha256(
        artifact_paths["operability_contract"]
    ):
        raise CompetitionRouteRuntimeError("可执行性报告未绑定当前合同")
    if operability_report["formal_result_sha256"] != selected_formal_sha:
        raise CompetitionRouteRuntimeError("可执行性报告未绑定选中路线 Formal Result")
    if risk_report["risk_decision_contract_sha256"] != _sha256(artifact_paths["risk_contract"]):
        raise CompetitionRouteRuntimeError("风险报告未绑定当前合同")
    if risk_report["formal_result_sha256"] != selected_formal_sha:
        raise CompetitionRouteRuntimeError("风险报告未绑定选中路线 Formal Result")

    codes: list[str] = []
    reasons: list[str] = []

    def add(code: str, reason: str) -> None:
        if code not in codes:
            codes.append(code)
            reasons.append(reason)

    if execution_report["status"] != "completed":
        add("G3V3_ROUTE_EXECUTION_INCOMPLETE", "至少一条路线的候选执行未完成。")
    if comparison_error is not None:
        add("G3V3_SELECTED_ROUTE_INADMISSIBLE", str(comparison_error))
    if any(item["data_leakage_detected"] for item in comparison["route_results"]):
        add("G3V3_DATA_LEAKAGE", "路线执行或比较证据检测到时间或数据泄漏。")
    if operability_report["overall_status"] != "passed":
        add("G3V3_OPERABILITY_FAILED", "选中方案存在未通过的硬可执行性检查。")
    if risk_report["overall_action"] == "block":
        add("G3V3_RISK_BLOCK", "风险独立报告要求阻断。")

    blocking = any(
        code
        in {
            "G3V3_ROUTE_EXECUTION_INCOMPLETE",
            "G3V3_SELECTED_ROUTE_INADMISSIBLE",
            "G3V3_DATA_LEAKAGE",
            "G3V3_OPERABILITY_FAILED",
            "G3V3_RISK_BLOCK",
        }
        for code in codes
    )
    if not blocking:
        if comparison["selection_status"] == "degraded":
            add("G3V3_ROUTE_DEGRADED", "路线比较只允许降级使用。")
        if risk_report["overall_action"] == "technical_report_only":
            add("G3V3_RISK_TECHNICAL_ONLY", "风险独立报告只允许技术报告。")
        if not all(item["formal_result_eligible"] for item in formal_results):
            add(
                "G3V3_FORMAL_RESULT_INELIGIBLE",
                "至少一条 Formal Result 未达到提交稿资格，仅可保留技术报告。",
            )

    if blocking:
        decision = "block"
    elif codes:
        decision = "technical_report_only"
    else:
        decision = "allow_paper"
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "competition_gate3_decision_v1",
        "run_id": model_route["run_id"],
        "subproblem_id": subproblem_id,
        "model_route_v3_sha256": model_sha,
        "route_execution_report_sha256": _sha256(artifact_paths["execution"]),
        "route_comparison_result_sha256": _sha256(artifact_paths["comparison"]),
        "operability_contract_sha256": _sha256(artifact_paths["operability_contract"]),
        "operability_report_sha256": _sha256(artifact_paths["operability_report"]),
        "risk_decision_contract_sha256": _sha256(artifact_paths["risk_contract"]),
        "risk_decision_report_sha256": _sha256(artifact_paths["risk_report"]),
        "formal_results": formal_results,
        "decision": decision,
        "paper_admission": decision == "allow_paper",
        "technical_report_allowed": True,
        "decision_codes": codes,
        "reasons": reasons,
        "validator": {
            "validator_id": validator_id,
            "independent_from_executor": validator_id != execution_report["executor_id"],
            "formal_result_authority": "collector_and_independent_validator",
        },
    }
    validate_artifact(report, context="full_replay")
    if write_report:
        output_path = parent_root / EVIDENCE_FILENAMES["decision"].format(
            subproblem_id=subproblem_id
        )
        _write_json_atomic(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--run-dir", required=True, type=Path)
    execute_parser.add_argument("--subproblem", required=True)
    execute_parser.add_argument("--executor-id", required=True)
    gate_parser = subparsers.add_parser("gate3")
    gate_parser.add_argument("--run-dir", required=True, type=Path)
    gate_parser.add_argument("--subproblem", required=True)
    gate_parser.add_argument("--validator-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "execute":
            result = execute_three_routes(args.run_dir, args.subproblem, args.executor_id)
        else:
            result = evaluate_competition_gate3(args.run_dir, args.subproblem, args.validator_id)
    except (CompetitionRouteRuntimeError, RouteContractError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status", result.get("decision")) in {"completed", "allow_paper"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
