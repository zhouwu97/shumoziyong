"""数学契约、执行复现和模型类型专项检查。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


OPTIMIZATION_REQUIREMENTS: dict[str, set[str]] = {
    "continuous_optimization": {
        "baseline", "feasibility", "constraint_residual", "bounds", "sensitivity"
    },
    "mip": {
        "baseline", "feasibility", "constraint_residual", "mip_gap", "bounds", "sensitivity"
    },
    "nonlinear_optimization": {
        "baseline", "feasibility", "constraint_residual", "kkt", "multi_start", "bounds", "sensitivity"
    },
    "heuristic": {
        "baseline",
        "feasibility",
        "constraint_residual",
        "multi_start",
        "bounds",
        "sensitivity",
    },
}
MANDATORY_OPTIMIZATION_CHECKS = {"feasibility", "constraint_residual", "bounds"}
CONDITIONAL_NA_CHECKS = {"mip_gap", "kkt", "multi_start"}


def _parse_execution_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_model_and_execution(
    result_report: Mapping[str, Any],
    result_manifest: Mapping[str, Any],
    *,
    run_dir: Path | None = None,
    claim_map: Mapping[str, Any] | None = None,
) -> list[str]:
    """返回全部可复核错误；结论只覆盖已配置检查。"""
    errors: list[str] = []
    contract = result_report.get("model_contract", {})
    variables = contract.get("variables", [])
    parameters = contract.get("parameters", [])
    variable_names = [item.get("name") for item in variables if isinstance(item, Mapping)]
    parameter_names = [item.get("name") for item in parameters if isinstance(item, Mapping)]
    if len(variable_names) != len(set(variable_names)):
        errors.append("变量定义存在重复符号")
    if len(parameter_names) != len(set(parameter_names)):
        errors.append("参数定义存在重复符号")
    defined_symbols = set(variable_names) | set(parameter_names)
    for formula in contract.get("formulas", []):
        unknown = set(formula.get("symbols", [])) - defined_symbols
        if unknown:
            errors.append(
                f"公式 {formula.get('formula_id')} 使用未定义符号：{sorted(unknown)}"
            )
    for unit_check in contract.get("unit_checks", []):
        if unit_check.get("compatible") is not True:
            errors.append(f"量纲检查未通过：{unit_check.get('expression')}")

    metric_names = {
        metric.get("name")
        for metric in result_report.get("metrics", [])
        if isinstance(metric, Mapping)
    }
    claim_bindings = contract.get("claim_result_bindings", [])
    for binding in claim_bindings:
        if binding.get("metric") not in metric_names:
            errors.append(
                f"Claim {binding.get('claim_id')} 绑定了不存在的结果指标 {binding.get('metric')}"
            )
    if claim_map is not None:
        claim_ids = {
            claim.get("claim_id")
            for claim in claim_map.get("claims", [])
            if isinstance(claim, Mapping)
        }
        bound_claims = {binding.get("claim_id") for binding in claim_bindings}
        if claim_ids != bound_claims:
            errors.append(
                "Claim-Result 绑定不完整："
                f"claims={sorted(str(item) for item in claim_ids)} "
                f"bindings={sorted(str(item) for item in bound_claims)}"
            )

    optimization = contract.get("optimization_checks", {})
    configured = set(optimization.get("configured", []))
    passed = set(optimization.get("passed", []))
    not_applicable = optimization.get("not_applicable", {})
    if configured != passed:
        errors.append(
            f"优化专项检查并非全部通过：configured={sorted(configured)} passed={sorted(passed)}"
        )
    model_type = contract.get("model_type")
    required = OPTIMIZATION_REQUIREMENTS.get(str(model_type), set())
    na_names = set(not_applicable) if isinstance(not_applicable, Mapping) else set()
    mandatory_na = MANDATORY_OPTIMIZATION_CHECKS & na_names
    for name in sorted(mandatory_na):
        errors.append(f"优化专项检查 {name} 不可豁免，必须配置并实际通过")
    unsupported_na = na_names - CONDITIONAL_NA_CHECKS - MANDATORY_OPTIMIZATION_CHECKS
    for name in sorted(unsupported_na):
        errors.append(f"优化专项检查 {name} 不支持标记为不适用")
    if isinstance(not_applicable, Mapping):
        for name, exemption in not_applicable.items():
            if not isinstance(exemption, Mapping):
                errors.append(f"优化专项检查 {name} 的 N/A 必须包含结构化原因和适用条件")
                continue
            reason = exemption.get("reason")
            condition = exemption.get("condition")
            if not isinstance(reason, str) or len(reason.strip()) < 10:
                errors.append(f"优化专项检查 {name} 的 N/A reason 不完整")
            if not isinstance(condition, str) or len(condition.strip()) < 10:
                errors.append(f"优化专项检查 {name} 的 N/A condition 不完整")
    covered = configured | (na_names & CONDITIONAL_NA_CHECKS)
    missing = required - covered
    if missing:
        errors.append(f"模型类型 {model_type} 缺少专项检查：{sorted(missing)}")

    if run_dir is not None:
        run_root = run_dir.resolve()
        for group in ("inputs", "outputs"):
            for item in result_manifest.get(group, []):
                path = (run_dir / str(item.get("path", ""))).resolve()
                if not path.is_relative_to(run_root) or not path.is_file():
                    errors.append(f"{group} 引用文件不存在或越界：{item.get('path')}")
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                    errors.append(f"{group} 文件 SHA-256 不匹配：{item.get('path')}")

    seeds = set(result_manifest.get("random_seeds", []))
    repeats = result_manifest.get("repeated_runs", [])
    execution_ids = [
        item.get("execution_id") for item in repeats if isinstance(item, Mapping)
    ]
    if (
        len(execution_ids) != len(repeats)
        or any(not isinstance(value, str) or not value.strip() for value in execution_ids)
        or len(execution_ids) != len(set(execution_ids))
    ):
        errors.append("重复运行 execution_id 必须非空且全局唯一")
    for item in repeats:
        if not isinstance(item, Mapping):
            errors.append("重复运行记录必须是对象")
            continue
        started = _parse_execution_time(item.get("started_at"))
        completed = _parse_execution_time(item.get("completed_at"))
        if started is None or completed is None:
            errors.append(f"重复运行 {item.get('execution_id')} 时间必须为带时区 ISO 8601")
        elif completed < started:
            errors.append(f"重复运行 {item.get('execution_id')} 完成时间早于开始时间")
    repeat_seeds = {item.get("seed") for item in repeats if isinstance(item, Mapping)}
    if not repeat_seeds.issubset(seeds):
        errors.append("重复运行使用了未声明随机种子")
    if result_manifest.get("deterministic_expected") is True:
        output_hashes = {
            item.get("output_sha256") for item in repeats if isinstance(item, Mapping)
        }
        if len(output_hashes) != 1:
            errors.append("声明确定性运行，但重复运行输出哈希不一致")
    elif len(repeat_seeds) < 2:
        errors.append("随机或非确定性模型的独立重复运行必须使用至少两个不同 seed")
    return errors
