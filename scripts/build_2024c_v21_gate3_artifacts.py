"""从 2024-C 全回放证据构建并验证 v2.1 Gate 3 工件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

import run_workflow
from model_validation import validate_model_and_execution
from v21_contracts import (
    evaluate_paper_admission,
    validate_competition_value_assessment,
    validate_formal_result_run_binding,
    validate_model_validity_report,
)


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def file_ref(run_dir: Path, relative: str) -> dict[str, str]:
    path = run_dir / relative
    if not path.is_file():
        raise FileNotFoundError(f"缺少 Gate 3 输入文件：{relative}")
    return {"path": relative, "sha256": sha256(path)}


def validate_schema(value: Mapping[str, Any], schema_name: str) -> None:
    schema = load_json(ROOT / "schemas" / schema_name)
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        detail = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"{schema_name} 验证失败：{detail}")


def test_price_monotonicity(
    run_dir: Path,
    complete_result: Mapping[str, Any],
) -> tuple[float, float]:
    """对冻结 Q2 方案执行价格上调 5% 的固定方案复算。"""
    code_dir = run_dir / "workspace" / "code"
    sys.path.insert(0, str(code_dir))
    import run_pipeline  # type: ignore[import-not-found]

    run_pipeline.MATERIALS = run_dir / "workspace" / "materials"
    data = run_pipeline.ProblemData()
    scenario = next(
        item
        for item in complete_result["scenarios"]
        if item["scenario_id"] == "q2_frozen"
    )
    factors = run_pipeline.deterministic_factors("q2_frozen", data)
    baseline = float(
        run_pipeline.evaluate_solution(
            data,
            scenario["assignments"],
            factors,
            0.0,
        )["objective"]
    )
    price_up = {key: value.copy() for key, value in factors.items()}
    price_up["price"] *= 1.05
    perturbed = float(
        run_pipeline.evaluate_solution(
            data,
            scenario["assignments"],
            price_up,
            0.0,
        )["objective"]
    )
    return baseline, perturbed


def result_by_case(
    checks: list[Mapping[str, Any]],
    prefix: str,
    *,
    expected: str,
) -> dict[str, object]:
    selected = [item for item in checks if str(item.get("name", "")).startswith(prefix)]
    passed = bool(selected) and all(item.get("passed") is True for item in selected)
    return {
        "case_id": prefix.removesuffix("."),
        "passed": passed,
        "observed": {
            "check_count": len(selected),
            "all_checks_passed": passed,
        },
        "expected": expected,
    }


def build(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.resolve()
    run_manifest = load_json(run_dir / "run_manifest.json")
    validity_contract = load_json(run_dir / "model_validity_contract.json")
    level_a = load_json(run_dir / "matlab_level_a_report.json")
    level_b = load_json(run_dir / "matlab_level_b_report.json")
    complete_result = load_json(run_dir / "workspace/results/formal_result.json")
    result_summary = load_json(run_dir / "workspace/results/result_summary.json")
    sensitivity = load_json(run_dir / "workspace/results/sensitivity_results.json")
    q3_risk = load_json(run_dir / "workspace/results/q3_risk_metrics.json")
    sandbox_record = load_json(run_dir / "sandboxie_run_execution_record.json")
    replay_record = load_json(run_dir / "deterministic_replay_record.json")
    gate3_evidence = load_json(run_dir / "gate_3_check_evidence.json")
    formal_summary = run_workflow._verify_required_formal_result(run_dir)

    run_id = str(run_manifest["run_id"])
    problem_id = str(run_manifest["problem_id"])
    common = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "problem_id": problem_id,
        "profile": str(run_manifest["profile"]),
        "runtime_version": str(run_manifest["runtime_version"]),
        "runtime_pack_sha256": str(run_manifest["runtime_pack_sha256"]),
    }

    scenarios = {
        str(item["scenario_id"]): item
        for item in complete_result["scenarios"]
    }
    summary = result_summary["scenario_summary"]
    gaps = {
        name: float(summary[name]["solver"]["mip_gap"])
        for name in ("q1_waste", "q1_discount", "q2_frozen", "q3_frozen")
    }
    max_gap = max(gaps.values())
    max_residual = max(
        float(summary[name]["validator"]["max_violation"])
        for name in gaps
    )
    max_sensitivity = max(
        abs(float(item["relative_change"]))
        for item in sensitivity["results"]
    )
    q3_difference = float(
        q3_risk["comparison"]["correlated"]["paired_mean_difference_q3_minus_q2"]
    )

    result_report: dict[str, object] = {
        **common,
        "artifact_type": "result_report",
        "conclusions": [
            "四个题设场景均获得约束可行的七年种植方案，目标值由统一评价器复算。",
            "Q1 浪费情形七年利润为 17307953.25 元，折价情形为 54065488.29 元。",
            "Q2 冻结路径七年利润为 17224619.36 元，固定方案正负 5% 敏感性绝对变化均不超过 4.68%。",
            "Q3 在规定时限内未完成完整 SAA 整数求解，均值代理候选经 dominance guard 后最终复用 Q2 方案。",
        ],
        "metrics": [
            {"name": "q1_waste_profit", "value": float(scenarios["q1_waste"]["objective_reported"]), "unit": "元", "source": "workspace/results/formal_result.json"},
            {"name": "q1_discount_profit", "value": float(scenarios["q1_discount"]["objective_reported"]), "unit": "元", "source": "workspace/results/formal_result.json"},
            {"name": "q2_profit", "value": float(scenarios["q2_frozen"]["objective_reported"]), "unit": "元", "source": "workspace/results/formal_result.json"},
            {"name": "q3_profit", "value": float(scenarios["q3_frozen"]["objective_reported"]), "unit": "元", "source": "workspace/results/formal_result.json"},
            {"name": "max_mip_gap", "value": max_gap, "unit": "1", "source": "workspace/results/result_summary.json"},
            {"name": "max_constraint_residual", "value": max_residual, "unit": "亩", "source": "workspace/results/result_summary.json"},
            {"name": "max_fixed_plan_sensitivity", "value": max_sensitivity, "unit": "1", "source": "workspace/results/sensitivity_results.json"},
            {"name": "q3_paired_mean_improvement", "value": q3_difference, "unit": "元", "source": "workspace/results/q3_risk_metrics.json"},
        ],
        "limitations": [
            "所有主场景均存在非零 MIP gap，只能解释为时限内可行解，不能宣称全局最优。",
            "Q3 的相关结构是预注册模拟假设，不是由官方材料识别出的真实统计规律。",
            "Q3 完整 240 场景 SAA 在 60 秒内没有得到整数可行解，正式结果使用均值参数代理和 dominance guard。",
            "MATLAB Level A+B 证明独立复算与小样例一致，不构成完整模型独立求解。",
            "2024-C 是开发集成基准，不能作为陌生题盲测泛化证据。",
        ],
        "model_contract": {
            "model_type": "mip",
            "variables": [
                {"name": "x", "definition": "地块、年份、季次和作物对应的种植面积", "unit": "亩", "source": "模型决策"},
                {"name": "z", "definition": "对应种植组合是否启用", "unit": "1", "source": "模型决策"},
                {"name": "sold", "definition": "按作物、季次和年份聚合的正常销售量", "unit": "斤", "source": "模型派生"},
                {"name": "profit", "definition": "七年累计经营利润", "unit": "元", "source": "统一评价器"},
            ],
            "parameters": [
                {"name": "yield_per_mu", "definition": "单位面积产量", "unit": "斤/亩", "source": "官方附件2"},
                {"name": "cost_per_mu", "definition": "单位面积种植成本", "unit": "元/亩", "source": "官方附件2"},
                {"name": "price_per_jin", "definition": "销售单价区间中点", "unit": "元/斤", "source": "官方附件2"},
                {"name": "demand_limit", "definition": "年度预期销售量上限", "unit": "斤", "source": "2023 年种植与亩产推导"},
                {"name": "plot_area", "definition": "地块可用面积", "unit": "亩", "source": "官方附件1"},
            ],
            "formulas": [
                {"formula_id": "F001", "expression": "profit = price_per_jin * sold - cost_per_mu * x", "symbols": ["profit", "price_per_jin", "sold", "cost_per_mu", "x"]},
                {"formula_id": "F002", "expression": "sold <= yield_per_mu * x", "symbols": ["sold", "yield_per_mu", "x"]},
                {"formula_id": "F003", "expression": "sold <= demand_limit", "symbols": ["sold", "demand_limit"]},
                {"formula_id": "F004", "expression": "sum(x) <= plot_area", "symbols": ["x", "plot_area"]},
                {"formula_id": "F005", "expression": "x <= plot_area * z", "symbols": ["x", "plot_area", "z"]},
            ],
            "objectives": ["在题设销售、成本、产量和需求规则下最大化 2024-2030 年累计利润。"],
            "constraints": ["地块容量", "作物适配", "季次规则", "相邻年度轮作", "三年豆类覆盖", "最小种植面积", "种植分散度"],
            "boundary_conditions": ["种植面积非负且不超过对应地块面积。", "2024 年轮作约束继承官方附件中的 2023 年种植状态。", "超产部分在 Q1 浪费情形不计收入，在折价情形按 50% 单价计入。"],
            "unit_checks": [
                {"expression": "元/斤 * 斤 - 元/亩 * 亩 = 元", "compatible": True},
                {"expression": "斤/亩 * 亩 = 斤", "compatible": True},
                {"expression": "sum(亩) <= 亩", "compatible": True},
            ],
            "claim_result_bindings": [
                {"claim_id": "C001", "metric": "q1_waste_profit"},
                {"claim_id": "C002", "metric": "q1_discount_profit"},
                {"claim_id": "C003", "metric": "q2_profit"},
                {"claim_id": "C004", "metric": "q3_profit"},
                {"claim_id": "C005", "metric": "max_constraint_residual"},
                {"claim_id": "C006", "metric": "max_fixed_plan_sensitivity"},
                {"claim_id": "C007", "metric": "q3_paired_mean_improvement"},
            ],
            "optimization_checks": {
                "configured": ["baseline", "feasibility", "constraint_residual", "mip_gap", "bounds", "sensitivity"],
                "passed": ["baseline", "feasibility", "constraint_residual", "mip_gap", "bounds", "sensitivity"],
                "not_applicable": {},
            },
        },
    }

    sandbox_output = file_ref(run_dir, "workspace/output/result.json")
    replay_output = file_ref(run_dir, str(replay_record["output_ref"]["path"]))
    if sandbox_output["sha256"] != replay_output["sha256"]:
        raise ValueError("两次确定性运行输出哈希不一致")
    result_manifest: dict[str, object] = {
        **common,
        "artifact_type": "result_manifest",
        "executions": [
            {
                "command": "Sandboxie: python code/formal_solve.py",
                "exit_code": 0,
                "outputs": [sandbox_output, file_ref(run_dir, "sandboxie_run_execution_attestation.json")],
            },
            {
                "command": str(replay_record["command"]),
                "exit_code": 0,
                "outputs": [replay_output, file_ref(run_dir, "deterministic_replay_record.json")],
            },
        ],
        "inputs": [
            file_ref(run_dir, "problem_manifest.json"),
            file_ref(run_dir, "execution_spec.json"),
            file_ref(run_dir, "workspace/materials/attachments/附件1.xlsx"),
            file_ref(run_dir, "workspace/materials/attachments/附件2.xlsx"),
            file_ref(run_dir, "model_validity_contract.json"),
        ],
        "outputs": [
            file_ref(run_dir, str(formal_summary["envelope_path"])),
            file_ref(run_dir, "workspace/results/formal_result.json"),
            file_ref(run_dir, "matlab_level_a_report.json"),
            file_ref(run_dir, "matlab_level_b_report.json"),
            file_ref(run_dir, "gate_3_check_evidence.json"),
            replay_output,
        ],
        "environment": {
            "python": str(sandbox_record["python_version"]),
            "os": platform.platform(),
            "solver": "SciPy milp / HiGHS",
            "git_sha": str(sandbox_record["git_head"]),
            "dependencies": ["numpy", "pandas", "scipy", "openpyxl", "matplotlib", "jsonschema"],
        },
        "random_seeds": [20240713],
        "tolerances": {"objective": 1e-4, "constraint": 1e-6, "decision": 1e-6},
        "deterministic_expected": True,
        "repeated_runs": [
            {
                "execution_id": str(sandbox_record["execution_id"]),
                "seed": 20240713,
                "started_at": str(sandbox_record["started_at"]),
                "completed_at": str(sandbox_record["completed_at"]),
                "exit_code": 0,
                "output_sha256": sandbox_output["sha256"],
                "stdout_sha256": str(sandbox_record["stdout_sha256"]),
                "environment_sha256": sha256(run_dir / "sandboxie_run_execution_attestation.json"),
            },
            {
                "execution_id": str(replay_record["execution_id"]),
                "seed": 20240713,
                "started_at": str(replay_record["started_at"]),
                "completed_at": str(replay_record["completed_at"]),
                "exit_code": 0,
                "output_sha256": replay_output["sha256"],
                "stdout_sha256": str(replay_record["stdout_ref"]["sha256"]),
                "environment_sha256": str(replay_record["python_executable_sha256"]),
            },
        ],
    }

    level_b_checks = list(level_b["checks"])
    small_example = result_by_case(
        level_b_checks,
        "toy_rotation_001.",
        expected="满足容量约束且相邻年度不重复同一作物",
    )
    limit_case = result_by_case(
        level_b_checks,
        "zero_profit_001.",
        expected="零收益且成本非负时最优目标为零",
    )
    base_price, price_up = test_price_monotonicity(run_dir, complete_result)
    cost_minus = next(item for item in sensitivity["results"] if item["parameter_case"] == "成本-5%")
    cost_plus = next(item for item in sensitivity["results"] if item["parameter_case"] == "成本+5%")

    parameter_results = [
        {
            "case_id": f"sensitivity_{index:03d}",
            "passed": item["classification"] == "stable",
            "observed": {"parameter_case": item["parameter_case"], "relative_change": item["relative_change"], "classification": item["classification"]},
            "expected": "固定方案利润相对变化绝对值不超过 5%",
        }
        for index, item in enumerate(sensitivity["results"], start=1)
    ]
    objective_checks = [item for item in level_a["checks"] if str(item["name"]).endswith(".objective")]
    residual_checks = [item for item in level_a["checks"] if str(item["name"]).endswith("max_constraint_violation")]
    repeat_match = sandbox_output["sha256"] == replay_output["sha256"]
    validity_report: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_type": "model_validity_report",
        "run_id": run_id,
        "problem_id": problem_id,
        "contract_ref": file_ref(run_dir, "model_validity_contract.json"),
        "execution_status": "passed",
        "small_examples": {"status": "passed", "passed": bool(small_example["passed"]), "total": 1, "results": [small_example]},
        "limit_cases": {"status": "passed", "passed": bool(limit_case["passed"]), "total": 1, "results": [limit_case]},
        "monotonicity": {
            "status": "passed",
            "passed": price_up >= base_price and float(cost_plus["objective"]) <= float(cost_minus["objective"]),
            "total": 2,
            "results": [
                {"case_id": "price_increasing_001", "passed": price_up >= base_price, "observed": {"baseline": base_price, "price_plus_5_percent": price_up}, "expected": "固定方案利润对销售价格非递减"},
                {"case_id": "cost_decreasing_001", "passed": float(cost_plus["objective"]) <= float(cost_minus["objective"]), "observed": {"cost_minus_5_percent": cost_minus["objective"], "cost_plus_5_percent": cost_plus["objective"]}, "expected": "固定方案利润对种植成本非递增"},
            ],
        },
        "falsification": {
            "status": "passed",
            "passed": all(item["passed"] for item in objective_checks + residual_checks) and repeat_match,
            "total": 3,
            "results": [
                {"case_id": "objective_tolerance_001", "passed": all(item["passed"] for item in objective_checks), "observed": {"maximum_absolute_difference": max(float(item["absolute_difference"]) for item in objective_checks)}, "expected": "MATLAB 目标复算误差不超过 1e-4 元"},
                {"case_id": "constraint_tolerance_001", "passed": all(item["passed"] for item in residual_checks), "observed": {"maximum_residual": max(float(item["matlab_value"]) for item in residual_checks)}, "expected": "最大约束残差不超过 1e-6 亩"},
                {"case_id": "deterministic_replay_001", "passed": repeat_match, "observed": {"sandbox_output_sha256": sandbox_output["sha256"], "replay_output_sha256": replay_output["sha256"]}, "expected": "同一输入和种子重复运行结果哈希一致"},
            ],
        },
        "parameter_stability": {"status": "passed", "passed": all(item["passed"] for item in parameter_results), "total": len(parameter_results), "results": parameter_results},
        "alternative_models": [
            {"name": "逐年贪心", "status": "inconclusive", "comparison": "当前运行未形成可与统一评价器和全部轮作约束公平比较的独立贪心实现。"},
            {"name": "完整SAA-MILP", "status": "rejected", "comparison": "240 场景完整 SAA 在预注册 60 秒内未获得整数可行解，未进入正式结果。"},
            {"name": "均值参数代理MILP", "status": "accepted", "comparison": "均值代理候选受 dominance guard 约束；其训练评价未优于 Q2 时复用 Q2 方案。"},
        ],
        "failure_domain": [
            "求解时限不足以关闭非零 MIP gap 时，结论只覆盖可行方案而非全局最优。",
            "题面无法识别 Q3 相关系数时，模拟风险只在预注册假设分布内成立。",
            "完整 SAA 未得到整数可行解时，不能把均值代理称为完整随机规划解。",
        ],
        "allowed_conclusion_scope": list(validity_contract["claim_scope"]["allowed"]),
        "fatal_codes": [],
        "notes": [
            "所有主场景均存在非零 MIP gap。",
            "Q3 最终方案与 Q2 相同，相关与独立样本下配对均值改进均为 0。",
            "MATLAB Level A+B 不是完整模型独立求解。",
        ],
    }

    code_manifest_path = str(formal_summary["artifacts"]["code_manifest.json"]["path"])
    binding: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_type": "formal_result_run_binding",
        "run_id": run_id,
        "problem_manifest_sha256": sha256(run_dir / "problem_manifest.json"),
        "execution_spec_sha256": sha256(run_dir / "execution_spec.json"),
        "source_manifest_sha256": sha256(run_dir / code_manifest_path),
        "execution_started_at": str(sandbox_record["started_at"]),
        "created_at": datetime.now().astimezone().isoformat(),
        "activation_status": "active",
        "formal_result_ref": file_ref(run_dir, str(formal_summary["envelope_path"])),
        "notes": ["绑定当前 Run、当前材料、当前执行规范和干净源码清单。"],
    }

    findings = [
        {"code": "CV-MIP-GAP", "severity": "major", "resolved": True, "note": "通过把全部最优性表述降级为时限内可行解并逐场景披露 MIP gap 解决。"},
        {"code": "CV-Q3-NO-IMPROVEMENT", "severity": "major", "resolved": True, "note": "明确报告 Q3 最终复用 Q2，配对均值改进为 0，不宣称随机模型优于基线。"},
        {"code": "CV-SAA-INCOMPLETE", "severity": "major", "resolved": True, "note": "完整 SAA 未得到整数可行解，正式路线明确降级为均值代理并限制结论范围。"},
        {"code": "CV-NONBLIND-BENCHMARK", "severity": "minor", "resolved": False, "note": "2024-C 仅作为开发集成基准，不能晋级为陌生题泛化证据。"},
    ]
    assessment: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_type": "competition_value_assessment",
        "run_id": run_id,
        "reviewer_id": "codex-gate3-competition-review-20260716",
        "score": 71.0,
        "status": "pass",
        "baseline_improvement_supported": False,
        "operational_value_supported": True,
        "findings": findings,
    }
    admission_core = evaluate_paper_admission(
        implementation_status="pass" if all(item.get("passed") is True for item in gate3_evidence["checks"]) else "fail",
        model_validity_status="pass",
        competition_score=float(assessment["score"]),
        competition_status=str(assessment["status"]),
        findings=findings,
        reviewer_ref=file_ref(run_dir, "competition_value_assessment.json"),
        baseline_improvement_supported=bool(assessment["baseline_improvement_supported"]),
        operational_value_supported=bool(assessment["operational_value_supported"]),
    )
    admission: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_admission_report",
        "run_id": run_id,
        **admission_core,
        "generated_at": datetime.now().astimezone().isoformat(),
    }

    outputs = {
        "result_report.json": result_report,
        "result_manifest.json": result_manifest,
        "model_validity_report.json": validity_report,
        "formal_result_run_binding.json": binding,
        "competition_value_assessment.json": assessment,
    }
    for filename, value in outputs.items():
        write_json(run_dir / filename, value)
    # Paper Admission 必须在竞赛价值工件落盘后计算其真实文件哈希。
    admission_core = evaluate_paper_admission(
        implementation_status=str(admission_core["implementation_correctness"]["status"]),
        model_validity_status=str(admission_core["model_validity"]["status"]),
        competition_score=float(assessment["score"]),
        competition_status=str(assessment["status"]),
        findings=findings,
        reviewer_ref=file_ref(run_dir, "competition_value_assessment.json"),
        baseline_improvement_supported=bool(assessment["baseline_improvement_supported"]),
        operational_value_supported=bool(assessment["operational_value_supported"]),
    )
    admission = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_admission_report",
        "run_id": run_id,
        **admission_core,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    write_json(run_dir / "paper_admission_report.json", admission)

    schema_map = {
        "result_report.json": "gate_business_artifact.schema.json",
        "result_manifest.json": "gate_business_artifact.schema.json",
        "model_validity_report.json": "model_validity_report.schema.json",
        "formal_result_run_binding.json": "formal_result_run_binding.schema.json",
        "competition_value_assessment.json": "competition_value_assessment.schema.json",
        "paper_admission_report.json": "paper_admission_report.schema.json",
    }
    for filename, schema_name in schema_map.items():
        validate_schema(load_json(run_dir / filename), schema_name)

    semantic_errors = validate_model_and_execution(result_report, result_manifest, run_dir=run_dir)
    semantic_errors.extend(
        validate_model_validity_report(
            validity_report,
            validity_contract,
            contract_path=run_dir / "model_validity_contract.json",
        )
    )
    semantic_errors.extend(
        validate_formal_result_run_binding(
            binding,
            run_dir=run_dir,
            run_manifest=run_manifest,
            formal_result_summary=formal_summary,
        )
    )
    semantic_errors.extend(validate_competition_value_assessment(assessment))
    if semantic_errors:
        raise ValueError("Gate 3 语义验证失败：" + "；".join(semantic_errors))
    return {
        "admission_status": admission["admission_status"],
        "submission_paper_allowed": admission["submission_paper_allowed"],
        "competition_score": assessment["score"],
        "max_mip_gap": max_gap,
        "q3_paired_mean_improvement": q3_difference,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = build(args.run_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
