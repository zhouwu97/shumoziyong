"""数学契约、执行复现和模型类型专项检查。"""

from __future__ import annotations

import hashlib
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
    "heuristic": {"baseline", "feasibility", "multi_start", "bounds", "sensitivity"},
}


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
                f"Claim-Result 绑定不完整：claims={sorted(claim_ids)} bindings={sorted(bound_claims)}"
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
    covered = configured | set(not_applicable)
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
    repeat_seeds = {item.get("seed") for item in repeats if isinstance(item, Mapping)}
    if not repeat_seeds.issubset(seeds):
        errors.append("重复运行使用了未声明随机种子")
    if result_manifest.get("deterministic_expected") is True:
        output_hashes = {
            item.get("output_sha256") for item in repeats if isinstance(item, Mapping)
        }
        if len(output_hashes) != 1:
            errors.append("声明确定性运行，但重复运行输出哈希不一致")
    return errors
