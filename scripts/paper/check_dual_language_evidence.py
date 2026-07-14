from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
KNOWN_ROLES = {
    "python": "primary_solver",
    "matlab": "independent_reproducer",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"证据文件顶层必须是对象: {path}")
    return payload


def add_issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    language: str | None = None,
) -> None:
    issue: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if language:
        issue["language"] = language
    issues.append(issue)


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def command_text(command: Any) -> str:
    if isinstance(command, str):
        return command.strip()
    if isinstance(command, list) and all(isinstance(item, str) for item in command):
        return " ".join(command).strip()
    return ""


def validate_package_records(
    records: Any,
    issues: list[dict[str, Any]],
    code: str,
    language: str,
    label: str,
) -> None:
    if not isinstance(records, list) or not records:
        add_issue(issues, "FAIL", code, f"缺少 {label} 记录", language)
        return
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not record.get("name") or not record.get("version"):
            add_issue(
                issues,
                "FAIL",
                f"invalid_{code}",
                f"第 {index} 条 {label} 记录缺少名称或版本",
                language,
            )


def validate_manifest(
    execution: dict[str, Any],
    field: str,
    missing_code: str,
    issues: list[dict[str, Any]],
    language: str,
) -> str | None:
    manifest = execution.get(field)
    if not isinstance(manifest, dict):
        add_issue(issues, "FAIL", missing_code, f"缺少 {field} 记录", language)
        return None
    if not isinstance(manifest.get("path"), str) or not manifest["path"].strip():
        add_issue(issues, "FAIL", f"invalid_{field}_path", f"{field} 缺少路径", language)
    digest = manifest.get("sha256")
    if not valid_sha256(digest):
        add_issue(issues, "FAIL", f"invalid_{field}_sha", f"{field} SHA-256 无效", language)
        return None
    return str(digest)


def validate_environment_blocker(
    execution: dict[str, Any], issues: list[dict[str, Any]], language: str
) -> None:
    blocker = execution.get("environment_blocker")
    if not isinstance(blocker, dict):
        add_issue(
            issues,
            "FAIL",
            "missing_environment_blocker",
            "blocked_environment 缺少环境探测记录",
            language,
        )
        return
    if not blocker.get("reason") or not command_text(blocker.get("probe_command")):
        add_issue(
            issues,
            "FAIL",
            "invalid_environment_blocker",
            "环境阻塞记录缺少原因或探测命令",
            language,
        )
    if not valid_sha256(blocker.get("observed_stderr_sha256")):
        add_issue(
            issues,
            "FAIL",
            "invalid_environment_probe_sha",
            "环境探测 stderr SHA-256 无效",
            language,
        )


def validate_execution_record(
    language: str,
    execution: dict[str, Any],
    expected_role: str | None,
    issues: list[dict[str, Any]],
) -> dict[str, str | None]:
    status = execution.get("status")
    verification_status = execution.get("verification_status")
    if status != "executed":
        if verification_status == "verified":
            add_issue(
                issues,
                "FAIL",
                "unexecuted_source_claimed_as_verified",
                "未执行的语言被标记为 verified",
                language,
            )
        if status == "blocked_environment":
            validate_environment_blocker(execution, issues, language)
            add_issue(
                issues,
                "BLOCKED",
                "blocked_environment",
                "语言运行环境不可用，双语言验证未完成",
                language,
            )
        else:
            add_issue(issues, "FAIL", "unexecuted_language", "语言未真实执行", language)
        return {"input_sha": None, "output_sha": None}

    if execution.get("execution_observed") is not True:
        add_issue(
            issues,
            "FAIL",
            "execution_not_observed",
            "缺少真实执行观测标记",
            language,
        )
        if verification_status == "verified":
            add_issue(
                issues,
                "FAIL",
                "unexecuted_source_claimed_as_verified",
                "没有执行观测却标记为 verified",
                language,
            )

    if execution.get("language") != language:
        add_issue(issues, "FAIL", "language_key_mismatch", "语言键与记录不一致", language)
    role = execution.get("role")
    if role != expected_role or role != KNOWN_ROLES.get(language, role):
        add_issue(issues, "FAIL", "invalid_language_role", "语言角色不符合 Profile", language)
    if not isinstance(execution.get("version"), str) or not execution["version"].strip():
        add_issue(issues, "FAIL", "missing_runtime_version", "缺少运行时版本", language)

    if language == "python":
        validate_package_records(
            execution.get("dependencies"),
            issues,
            "missing_dependency_record",
            language,
            "依赖",
        )
    elif language == "matlab":
        validate_package_records(
            execution.get("toolboxes"),
            issues,
            "missing_toolbox_record",
            language,
            "MATLAB 工具箱",
        )

    command = command_text(execution.get("command"))
    if not command:
        add_issue(issues, "FAIL", "missing_execution_command", "缺少实际执行命令", language)
    if not isinstance(execution.get("cwd"), str) or not execution["cwd"].strip():
        add_issue(issues, "FAIL", "missing_execution_cwd", "缺少实际工作目录", language)

    started_at = parse_timestamp(execution.get("started_at"))
    ended_at = parse_timestamp(execution.get("ended_at"))
    if started_at is None or ended_at is None:
        add_issue(
            issues, "FAIL", "invalid_execution_time", "执行时间缺失、无时区或格式错误", language
        )
    elif ended_at < started_at:
        add_issue(issues, "FAIL", "invalid_execution_time_order", "结束时间早于开始时间", language)

    exit_code = execution.get("exit_code")
    if not isinstance(exit_code, int):
        add_issue(issues, "FAIL", "missing_exit_code", "缺少整数退出码", language)
    elif exit_code != 0:
        add_issue(issues, "FAIL", "nonzero_exit_code", f"执行退出码为 {exit_code}", language)

    for stream in ("stdout", "stderr"):
        if not valid_sha256(execution.get(f"{stream}_sha256")):
            add_issue(
                issues,
                "FAIL",
                f"invalid_{stream}_sha",
                f"{stream} SHA-256 缺失或无效",
                language,
            )

    validate_manifest(execution, "source_manifest", "missing_source_manifest", issues, language)
    input_sha = validate_manifest(
        execution, "input_manifest", "missing_input_manifest", issues, language
    )
    output_sha = validate_manifest(
        execution, "output_manifest", "missing_output_manifest", issues, language
    )

    if language == "matlab":
        isolation = execution.get("isolation")
        if not isinstance(isolation, dict):
            add_issue(issues, "FAIL", "missing_matlab_isolation", "缺少 MATLAB 隔离记录", language)
        else:
            if isolation.get("invokes_python") is not False or re.search(
                r"\bpython(?:\.exe)?\b", command, flags=re.IGNORECASE
            ):
                add_issue(
                    issues,
                    "FAIL",
                    "matlab_invokes_python",
                    "MATLAB 证据显示调用了 Python",
                    language,
                )
            if isolation.get("reads_python_intermediates") is not False:
                add_issue(
                    issues,
                    "FAIL",
                    "matlab_reads_python_intermediates",
                    "MATLAB 证据显示读取了 Python 中间量",
                    language,
                )
            if isolation.get("input_origin") != "shared_official_inputs":
                add_issue(
                    issues,
                    "FAIL",
                    "invalid_matlab_input_origin",
                    "MATLAB 输入来源不是共同原始输入",
                    language,
                )

    return {"input_sha": input_sha, "output_sha": output_sha}


def validate_execution_evidence(
    evidence: dict[str, Any], issues: list[dict[str, Any]]
) -> dict[str, dict[str, str | None]]:
    if evidence.get("example_only") is True:
        add_issue(issues, "FAIL", "example_payload_not_evidence", "示例文件不能作为真实执行证据")

    profile = evidence.get("profile")
    if not isinstance(profile, dict):
        add_issue(issues, "FAIL", "missing_execution_profile", "缺少比赛执行 Profile")
        return {}
    required = profile.get("required_languages")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(x, str) for x in required)
    ):
        add_issue(
            issues, "FAIL", "invalid_required_languages", "required_languages 必须是非空字符串列表"
        )
        return {}
    languages = [language.lower() for language in required]
    if len(languages) != len(set(languages)):
        add_issue(issues, "FAIL", "duplicate_required_language", "required_languages 存在重复项")

    roles = profile.get("language_roles")
    if not isinstance(roles, dict):
        add_issue(issues, "FAIL", "missing_language_roles", "缺少 language_roles")
        roles = {}
    executions = evidence.get("executions")
    if not isinstance(executions, dict):
        add_issue(issues, "FAIL", "missing_executions", "缺少 executions 对象")
        executions = {}

    records: dict[str, dict[str, str | None]] = {}
    for language in languages:
        execution = executions.get(language)
        if not isinstance(execution, dict):
            add_issue(
                issues,
                "FAIL",
                f"missing_{language}_execution",
                f"缺少 {language} 真实执行记录",
                language,
            )
            continue
        records[language] = validate_execution_record(
            language, execution, roles.get(language), issues
        )

    python_input = records.get("python", {}).get("input_sha")
    matlab_input = records.get("matlab", {}).get("input_sha")
    if python_input and matlab_input and python_input != matlab_input:
        add_issue(
            issues,
            "FAIL",
            "cross_language_input_manifest_mismatch",
            "Python 与 MATLAB 没有使用同一输入 Manifest",
        )
    return records


def decimal_value(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def values_match(left: Any, right: Any, absolute: Any, relative: Any) -> bool:
    left_value = decimal_value(left)
    right_value = decimal_value(right)
    absolute_tolerance = decimal_value(absolute)
    relative_tolerance = decimal_value(relative)
    if None in {left_value, right_value, absolute_tolerance, relative_tolerance}:
        return False
    assert left_value is not None
    assert right_value is not None
    assert absolute_tolerance is not None
    assert relative_tolerance is not None
    if absolute_tolerance < 0 or relative_tolerance < 0:
        return False
    difference = abs(left_value - right_value)
    scale = max(abs(left_value), abs(right_value))
    return difference <= max(absolute_tolerance, relative_tolerance * scale)


def validate_cross_language_evidence(
    validation: dict[str, Any],
    execution: dict[str, Any],
    records: dict[str, dict[str, str | None]],
    issues: list[dict[str, Any]],
) -> None:
    if validation.get("example_only") is True:
        add_issue(
            issues, "FAIL", "example_payload_not_evidence", "示例文件不能作为真实交叉验证证据"
        )
    if validation.get("execution_evidence_id") != execution.get("evidence_id"):
        add_issue(issues, "FAIL", "execution_evidence_id_mismatch", "交叉验证未绑定当前执行证据")

    output_manifests = validation.get("output_manifests")
    if not isinstance(output_manifests, dict):
        add_issue(issues, "FAIL", "missing_cross_output_manifests", "缺少跨语言输出 Manifest 引用")
    else:
        for language in ("python", "matlab"):
            expected = records.get(language, {}).get("output_sha")
            actual = output_manifests.get(f"{language}_sha256")
            if expected != actual or not valid_sha256(actual):
                add_issue(
                    issues,
                    "FAIL",
                    "cross_output_manifest_mismatch",
                    f"{language} 输出 Manifest 与执行证据不一致",
                    language,
                )

    objective = validation.get("objective")
    if not isinstance(objective, dict):
        add_issue(issues, "FAIL", "missing_objective_comparison", "缺少目标值比较")
    elif not values_match(
        objective.get("python_value"),
        objective.get("matlab_value"),
        objective.get("absolute_tolerance"),
        objective.get("relative_tolerance"),
    ):
        add_issue(
            issues,
            "FAIL",
            "cross_language_objective_mismatch",
            "Python 与 MATLAB 的目标值超过允许容差",
        )

    constraints = validation.get("hard_constraints")
    if not isinstance(constraints, list) or not constraints:
        add_issue(issues, "FAIL", "missing_hard_constraint_comparison", "缺少硬约束比较")
    else:
        for index, constraint in enumerate(constraints, start=1):
            mismatch = not isinstance(constraint, dict)
            if not mismatch:
                python_result = constraint.get("python")
                matlab_result = constraint.get("matlab")
                tolerance = decimal_value(constraint.get("violation_tolerance"))
                if not isinstance(python_result, dict) or not isinstance(matlab_result, dict):
                    mismatch = True
                else:
                    python_violation = decimal_value(python_result.get("max_violation"))
                    matlab_violation = decimal_value(matlab_result.get("max_violation"))
                    mismatch = (
                        python_result.get("satisfied") is not True
                        or matlab_result.get("satisfied") is not True
                        or tolerance is None
                        or tolerance < 0
                        or python_violation is None
                        or matlab_violation is None
                        or python_violation > tolerance
                        or matlab_violation > tolerance
                    )
            if mismatch:
                constraint_id = (
                    constraint.get("constraint_id", index)
                    if isinstance(constraint, dict)
                    else index
                )
                add_issue(
                    issues,
                    "FAIL",
                    "hard_constraint_mismatch",
                    f"硬约束比较失败: {constraint_id}",
                )

    aggregates = validation.get("business_aggregates")
    if not isinstance(aggregates, list) or not aggregates:
        add_issue(issues, "FAIL", "missing_business_aggregate_comparison", "缺少业务聚合量比较")
    else:
        for index, aggregate in enumerate(aggregates, start=1):
            if not isinstance(aggregate, dict) or not values_match(
                aggregate.get("python_value") if isinstance(aggregate, dict) else None,
                aggregate.get("matlab_value") if isinstance(aggregate, dict) else None,
                aggregate.get("absolute_tolerance") if isinstance(aggregate, dict) else None,
                aggregate.get("relative_tolerance") if isinstance(aggregate, dict) else None,
            ):
                aggregate_id = (
                    aggregate.get("aggregate_id", index) if isinstance(aggregate, dict) else index
                )
                add_issue(
                    issues,
                    "FAIL",
                    "business_aggregate_mismatch",
                    f"业务聚合量比较失败: {aggregate_id}",
                )

    optimality = validation.get("optimality")
    if not isinstance(optimality, dict) or not optimality.get("python_status"):
        add_issue(issues, "FAIL", "missing_optimality_comparison", "缺少最优性状态比较")
    elif optimality.get("python_status") != optimality.get("matlab_status"):
        add_issue(
            issues,
            "FAIL",
            "optimality_status_mismatch",
            "Python 与 MATLAB 的最优性状态不一致",
        )

    variables = validation.get("decision_variables")
    if not isinstance(variables, dict):
        add_issue(issues, "FAIL", "missing_decision_variable_comparison", "缺少决策变量比较模式")
        return
    mode = variables.get("comparison_mode")
    python_sha = variables.get("python_manifest_sha256")
    matlab_sha = variables.get("matlab_manifest_sha256")
    if not valid_sha256(python_sha) or not valid_sha256(matlab_sha):
        add_issue(
            issues, "FAIL", "invalid_decision_variable_manifest", "决策变量 Manifest SHA 无效"
        )
    if mode == "exact" and python_sha != matlab_sha:
        add_issue(issues, "FAIL", "decision_variable_mismatch", "exact 模式要求决策变量完全一致")
    elif mode not in {"exact", "equivalent_optimum"}:
        add_issue(issues, "FAIL", "invalid_variable_comparison_mode", "未知的决策变量比较模式")


def check_dual_language_evidence(
    execution: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    records = validate_execution_evidence(execution, issues)
    profile = execution.get("profile")
    required_raw = profile.get("required_languages", []) if isinstance(profile, dict) else []
    required_languages = {
        str(language).lower() for language in required_raw if isinstance(language, str)
    }
    cross_validation_required = {"python", "matlab"}.issubset(required_languages)
    execution_failures = any(issue["severity"] == "FAIL" for issue in issues)
    blocked = any(issue["severity"] == "BLOCKED" for issue in issues)
    if cross_validation_required and not execution_failures and not blocked:
        validate_cross_language_evidence(validation, execution, records, issues)

    failures = [issue for issue in issues if issue["severity"] == "FAIL"]
    blockers = [issue for issue in issues if issue["severity"] == "BLOCKED"]
    if failures:
        status = "failed"
    elif blockers:
        status = "blocked_environment"
    else:
        status = "passed"
    return {
        "schema_version": "1.0.0",
        "passed": status == "passed",
        "status": status,
        "evidence_id": execution.get("evidence_id"),
        "validation_id": validation.get("validation_id"),
        "summary": {
            "failures": len(failures),
            "blockers": len(blockers),
            "issues": len(issues),
        },
        "issues": issues,
        "required_languages": sorted(required_languages),
        "cross_language_validation_required": cross_validation_required,
        "solver_execution_performed_by_checker": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证双语言真实执行与交叉验证证据合同")
    parser.add_argument("--execution", type=Path, required=True, help="双语言执行证据 JSON")
    parser.add_argument("--validation", type=Path, required=True, help="跨语言验证证据 JSON")
    parser.add_argument("--output", type=Path, default=Path("dual_language_check.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = check_dual_language_evidence(load_json(args.execution), load_json(args.validation))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    if report["status"] == "passed":
        return 0
    if report["status"] == "blocked_environment":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
