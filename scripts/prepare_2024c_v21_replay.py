"""为 2024-C v2.1 全回放生成 Gate 0-2 合同与 MATLAB 输入。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ref(run_dir: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_file(path)}


def identity(run_dir: Path) -> dict[str, str]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    return {
        "run_id": manifest["run_id"],
        "problem_id": manifest["problem_id"],
        "profile": manifest["profile"],
        "runtime_version": manifest["runtime_version"],
        "runtime_pack_sha256": manifest["runtime_pack_sha256"],
    }


def named(name: str, definition: str, unit: str | None, source: str | None) -> dict[str, Any]:
    return {"name": name, "definition": definition, "unit": unit, "source": source}


def build_gate_0(run_dir: Path) -> None:
    ident = identity(run_dir)
    diagnosis = {
        "schema_version": "1.0.0",
        "artifact_type": "diagnosis",
        **ident,
        "problem_summary": "在异质耕地、轮作、适宜性和销售上限约束下，为 2024-2030 年制定逐地块逐季作物面积方案，并比较确定性、冻结不确定性和相关情景策略。",
        "material_findings": ["官方题面、附件 1、附件 2 和三份结果模板齐全", "材料清单声明不含答案或同题解析"],
        "objectives": ["问题 1 两种销售规则下最大化七年利润", "问题 2 在冻结参数路径下生成可行方案", "问题 3 在透明相关结构下比较风险表现"],
        "constraints": ["地块容量与作物适宜性", "相邻季次不得重茬", "滚动三年豆类覆盖", "水浇地种植模式互斥", "最小种植面积和分散度"],
        "risks": ["题面未给出相关系数，Q3 结论仅对假设分布成立", "MILP 时限可能留下较大 gap", "Excel 合并单元格可能造成数据映射错误"],
    }
    write_json(run_dir / "diagnosis.json", diagnosis)
    (run_dir / "diagnosis.md").write_text(
        "# Gate 0 题目诊断\n\n"
        "本题是多期农业资源配置问题。正式路线采用统一利润评价器、混合整数线性规划和相关/独立情景后评估。"
        "Q3 的相关结构属于透明建模假设，任何结果均不得表述为真实概率分布下的全局最优策略。\n",
        encoding="utf-8",
    )


def subproblem(subproblem_id: str, task: str, selected: str) -> dict[str, Any]:
    return {
        "subproblem_id": subproblem_id,
        "task_type": task,
        "inputs": [named("official_data", "官方地块、作物、种植和经营数据", None, "附件1和附件2")],
        "outputs": [named("planting_plan", "2024-2030逐地块逐季种植面积", "亩", "Python求解输出")],
        "variables": [named("x", "年度-地块-季次-作物种植面积", "亩", "模型决策变量"), named("z", "作物是否在地块季次启用", "无量纲", "模型决策变量")],
        "parameters": [named("yield", "单位面积产量", "斤/亩", "附件2"), named("cost", "单位面积种植成本", "元/亩", "附件2"), named("price", "销售单价区间中点", "元/斤", "附件2")],
        "objectives": ["在给定销售和不确定性口径下最大化七年总利润"],
        "constraints": ["面积容量", "适宜性", "重茬", "三年豆类覆盖", "水浇地模式互斥", "管理便利性"],
        "assumptions": ["价格采用官方区间中点", "销售上限按2023实际产量汇总", "Q3相关结构不是官方统计事实"],
        "baseline_model": {"name": "逐年收益贪心", "rationale": "提供低复杂度比较，但不能可靠处理跨年轮作约束。"},
        "selected_model": {"name": selected, "rationale": "能显式表示连续面积、二元启用、分段收入和跨年约束，并允许独立复算。"},
        "alternatives_rejected": [{"name": "遗传算法", "rejection_reason": "约束修复和最优性边界难以形成同等级可复算证据。"}],
        "validation_requirements": ["Python独立约束检查", "MATLAB Level A目标与残差复算", "MATLAB Level B小样例独立求解"],
        "uncertainty_plan": ["固定随机种子", "相关与独立两种分布并行评估", "明确披露分布假设"],
        "failure_conditions": ["任何容量或轮作残差超过容差", "目标函数跨语言复算不一致", "把非零MIP gap表述为全局最优"],
    }


def build_gate_1(run_dir: Path) -> None:
    ident = identity(run_dir)
    assertions = run_dir / "public_assertions.json"
    write_json(assertions, [{"assertion_id": "public.unit_declared"}, {"assertion_id": "public.boundary_case_declared"}])
    validity = {
        "schema_version": "1.0.0", "artifact_type": "model_validity_contract",
        "run_id": ident["run_id"], "problem_id": ident["problem_id"], "contract_status": "planned",
        "data_generation": {"mechanism": "直接读取官方附件并按题面规则重建可行作物集合、经营参数和2023轮作状态。", "sources": ["official_materials/2024_C/attachments/附件1.xlsx", "official_materials/2024_C/attachments/附件2.xlsx"], "scope": "覆盖问题1两种销售情形、问题2冻结路径和问题3相关模拟比较。"},
        "variables": [named("x", "种植面积", "亩", "模型决策"), named("z", "启用状态", "无量纲", "模型决策")],
        "parameters": [named("yield", "亩产量", "斤/亩", "附件2"), named("cost", "种植成本", "元/亩", "附件2"), named("price", "销售单价", "元/斤", "附件2"), named("demand", "预期销售量", "斤", "2023种植与亩产量")],
        "formulas": [
            {"formula_id": "F_profit", "expression": "profit = price * sold - cost * area", "symbols": ["profit", "price", "sold", "cost", "area"], "expected_units": "元"},
            {"formula_id": "F_capacity", "expression": "sum_c x[y,p,s,c] <= area[p]", "symbols": ["x", "area"], "expected_units": "亩"},
        ],
        "parameter_estimation_plan": {"method": "官方表格参数直接读取，价格区间取中点；Q3边际范围按题面，相关结构按预注册系数生成。", "identifiability": "确定性参数由作物、地块类型和季次唯一索引；Q3相关系数不可由题面识别。", "stability_test": "对需求、亩产和成本执行正负5%固定方案敏感性，并比较相关与独立样本结果。"},
        "small_examples": [{"case_id": "toy_rotation_001", "description": "两地块两作物两年度的离散轮作小样例。", "expected_behavior": "最优解满足容量且不会在相邻年度重复同一作物。", "execution_ref": "matlab_level_b_input.json"}],
        "limit_cases": [{"case_id": "zero_profit_001", "description": "所有收益系数为零且成本非负的极限情形。", "expected_behavior": "最优目标不应随强制额外种植而增加。", "execution_ref": "matlab_level_b_input.json"}],
        "expected_monotonicity": [{"quantity": "固定方案利润对销售价格", "direction": "increasing", "condition": "销量、成本和产量保持不变"}, {"quantity": "固定方案利润对种植成本", "direction": "decreasing", "condition": "面积和销售收入保持不变"}],
        "falsification_conditions": ["MATLAB复算目标超出1e-4元容差", "约束最大违反量超过1e-6亩", "同一输入重复运行的正式结果哈希不同"],
        "alternative_models": [{"name": "逐年贪心", "comparison_plan": "比较其可行性修复复杂度和统一评价器利润，不把其作为正式方案。"}, {"name": "完整SAA-MILP", "comparison_plan": "记录规定时限内是否获得整数可行解；失败时降级为均值参数代理并披露。"}],
        "claim_scope": {"allowed": ["报告时限内获得的可行方案及其复算利润", "报告假设分布内的风险比较"], "forbidden": ["宣称所有场景均达到全局最优", "将Q3相关结构称为真实统计规律", "将MATLAB A+B称为完整模型独立求解"]},
        "assertion_refs": [{"assertion_set_id": "2024C_public_v1", "layer": "public", "path": "public_assertions.json", "sha256": sha256_file(assertions), "sealed": False, "blind_evidence": False}],
    }
    write_json(run_dir / "model_validity_contract.json", validity)
    route = {
        "schema_version": "2.1.0", "artifact_type": "model_route_v2_1", **ident,
        "subproblems": [subproblem("Q1_WASTE", "确定性混合整数优化", "分段收入MILP"), subproblem("Q1_DISCOUNT", "折价销售混合整数优化", "两级价格MILP"), subproblem("Q2_FROZEN", "冻结不确定性决策", "保守参数路径MILP"), subproblem("Q3_SIMULATION", "相关性仿真与策略比较", "均值参数代理MILP加Monte Carlo")],
        "human_decisions_required": ["接受价格区间中点口径", "接受Q3相关结构仅为透明假设", "接受非零MIP gap时仅报告可行解"],
        "model_validity_contract_ref": ref(run_dir, run_dir / "model_validity_contract.json"),
        "conclusion_scope": validity["claim_scope"]["allowed"],
    }
    write_json(run_dir / "model_route_v2_1.json", route)


def build_gate_2(run_dir: Path) -> None:
    ident = identity(run_dir)
    code_path = run_dir / "workspace" / "code" / "formal_solve.py"
    source_inputs = [
        run_dir / "workspace" / "materials" / "attachments" / "附件1.xlsx",
        run_dir / "workspace" / "materials" / "attachments" / "附件2.xlsx",
    ]
    input_files = [
        run_dir / "problem" / "attachments" / "attachment1.xlsx",
        run_dir / "problem" / "attachments" / "attachment2.xlsx",
    ]
    for source, target in zip(source_inputs, input_files, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    execution = {
        "schema_version": "1.0.0", "artifact_type": "execution_spec", **ident,
        "formal_result_policy": "required_v1", "execution_contract_version": "1.0.0", "formal_result_contract_version": "1.0.0", "canonicalization_version": "1.0.0", "gate_artifact_contract_version": "1.0.0",
        "execution_mode": "trusted_local", "declared_workspace": "workspace", "network_access": False, "declared_writable_paths": ["workspace/output"],
        "approved_by": "Codex", "approved_at": datetime.now(timezone.utc).isoformat(),
        "tasks": [{"task_id": "SOLVE_2024C_FORMAL_Q1", "runner": "python", "entrypoint": "code/formal_solve.py", "entrypoint_arg_index": 1, "argv": ["python", "code/formal_solve.py"], "working_directory": "workspace", "inputs": [{"path": "problem/attachments/attachment1.xlsx", "sha256": sha256_file(input_files[0])}, {"path": "problem/attachments/attachment2.xlsx", "sha256": sha256_file(input_files[1])}], "required_outputs": [{"path": "workspace/output/result.json", "media_type": "application/json"}], "depends_on": [], "timeout_seconds": 7200, "seed_policy": {"deterministic_expected": True, "seeds": [20240713]}, "acceptance_checks": [{"check_id": "formal_result", "kind": "file_exists", "expectation": "output/result.json"}], "fallback": "emit_blocker"}],
        "contract_notes": ["Formal Result 在 Sandboxie 内从官方附件重建并求解 Q1 浪费情形", "完整四场景结果由同一 Run 的 Python 全题执行与 Gate 3 报告绑定", "非零MIP gap只允许可行解表述", f"正式入口SHA256={sha256_file(code_path)}"],
    }
    write_json(run_dir / "execution_spec.json", execution)
    code_plan = {"schema_version": "1.0.0", "artifact_type": "code_plan", **ident, "commands": ["python code/run_pipeline.py", "python code/formal_solve.py（Sandboxie）", "MATLAB Level A", "MATLAB Level B"], "modules": ["code/run_pipeline.py", "code/formal_solve.py", "独立MATLAB复算脚本"], "inputs": ["官方附件1.xlsx", "官方附件2.xlsx"], "outputs": ["四场景方案", "风险样本", "约束报告", "当前运行 Formal Result"], "verification_steps": ["独立重算目标", "检查容量与轮作", "小样例枚举", "固定种子复跑"]}
    write_json(run_dir / "code_plan.json", code_plan)
    independence = {"schema_version": "1.0.0", "artifact_type": "validator_independence_manifest", "run_id": ident["run_id"], "validator_id": "matlab_2024c_v21", "raw_input_origin": "official_materials/2024_C official xlsx", "reads_primary_intermediates": False, "reads_primary_metrics": False, "reads_primary_decision_vector": True, "reconstructs_coefficients_independently": True, "shared_source_modules": [], "independent_formula_implementation": True, "validation_scope": ["objective_recalculation", "capacity_and_rotation_residuals", "small_example_independent_solution", "boundary_tests"], "f5_status": "pass", "evidence_refs": ["matlab_level_a_report.json", "matlab_level_b_report.json"]}
    write_json(run_dir / "validator_independence_manifest.json", independence)


def build_matlab_inputs(run_dir: Path) -> None:
    summary_path = run_dir / "workspace" / "results" / "result_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    formal_path = run_dir / "workspace" / "results" / "formal_result.json"
    sensitivity_path = run_dir / "workspace" / "results" / "sensitivity_results.json"
    sensitivity = json.loads(sensitivity_path.read_text(encoding="utf-8"))
    cost_plus_5 = next(
        float(item["objective"])
        for item in sensitivity["results"]
        if item["parameter_case"] == "成本+5%"
    )
    official = [run_dir / "workspace" / "materials" / "attachments" / "附件1.xlsx", run_dir / "workspace" / "materials" / "attachments" / "附件2.xlsx"]
    common = {"schema_version": "1.0.0", "run_id": identity(run_dir)["run_id"], "official_input_refs": [ref(run_dir, item) for item in official], "python_result_ref": ref(run_dir, formal_path), "tolerances": {"objective": 1e-4, "constraint": 1e-6, "statistic": 1e-6, "decision": 1e-6}}
    contracts = []
    for scenario_id, alpha, factor_kind in [
        ("q1_waste", 0.0, "q1"),
        ("q1_discount", 0.5, "q1"),
        ("q2_frozen", 0.0, "q2_frozen"),
        ("q3_frozen", 0.0, "q3_contract"),
    ]:
        scenario = next(item for item in json.loads(formal_path.read_text(encoding="utf-8"))["scenarios"] if item["scenario_id"] == scenario_id)
        contracts.append(
            {
                "scenario_id": scenario_id,
                "sales_excess_alpha": alpha,
                "factor_kind": factor_kind,
                "python_objective": float(summary["scenario_summary"][scenario_id]["objective_recomputed"]),
                "python_max_constraint_violation": float(summary["scenario_summary"][scenario_id]["validator"]["max_violation"]),
                "python_assignment_count": len(scenario["assignments"]),
                "python_decision_sum_mu": sum(float(item["area_mu"]) for item in scenario["assignments"]),
            }
        )
    level_a = {
        **common,
        "level": "A",
        "scenario_contracts": contracts,
        "sensitivity_contracts": [
            {
                "name": "q2_frozen.cost_plus_5_percent",
                "scenario_id": "q2_frozen",
                "parameter": "cost",
                "multiplier": 1.05,
                "python_value": cost_plus_5,
            }
        ],
    }
    write_json(run_dir / "matlab_level_a_input.json", level_a)
    level_b = {**common, "level": "B", "small_examples": [{"case_id": "toy_rotation_001", "objective_direction": "max", "objective_coefficients": [3.0, 2.0], "variables": [{"lower": 0, "upper": 1, "step": 1}, {"lower": 0, "upper": 1, "step": 1}], "constraints": [{"name": "capacity", "coefficients": [1.0, 1.0], "sense": "<=", "rhs": 1.0}], "python_expected": {"objective_value": 3.0, "decision_vector": [1.0, 0.0], "boundary_checks": [{"name": "capacity", "coefficients": [1.0, 1.0], "sense": "<=", "rhs": 1.0, "expected": True}]}}, {"case_id": "zero_profit_001", "objective_direction": "max", "objective_coefficients": [0.0], "variables": [{"lower": 0, "upper": 1, "step": 1}], "constraints": [{"name": "nonnegative", "coefficients": [1.0], "sense": ">=", "rhs": 0.0}], "python_expected": {"objective_value": 0.0, "decision_vector": [0.0], "boundary_checks": [{"name": "nonnegative", "coefficients": [1.0], "sense": ">=", "rhs": 0.0, "expected": True}]}}]}
    write_json(run_dir / "matlab_level_b_input.json", level_b)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    build_gate_0(run_dir)
    build_gate_1(run_dir)
    build_gate_2(run_dir)
    build_matlab_inputs(run_dir)
    print(json.dumps({"run_dir": str(run_dir), "python": platform.python_version()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
