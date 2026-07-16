"""构建 PR-7 五题、17 个子问题和 51 个独立路线子 Run。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.hashing import file_sha256
from initialize_formal_result import initialize_formal_result
from route_contract_dispatch import validate_artifact


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (
    ("R-BASE", "baseline"),
    ("R-PRIMARY", "primary"),
    ("R-ALT", "structural_alternative"),
)


PROBLEMS: dict[str, dict[str, Any]] = {
    "2016-C": {
        "run": "pr7-2016c-full-replay-20260717",
        "profile": "prediction",
        "material": "2016_C",
        "subproblems": [
            ("Q1", "分电流放电曲线与剩余时间", "prediction", "放电电压随时间单调非线性下降，初等函数可逼近该响应。"),
            ("Q2", "任意恒流放电曲线", "prediction", "电流强度通过容量衰减率连续调制放电曲线形状。"),
            ("Q3", "衰减状态剩余放电时间", "prediction", "老化状态改变有效容量但保持放电曲线的主要形状机制。"),
        ],
    },
    "2023-B": {
        "run": "pr7-2023b-full-replay-20260717",
        "profile": "engineering_optimization",
        "material": "2023_B",
        "subproblems": [
            ("Q1", "坡面覆盖宽度与重叠率", "survey", "坡度改变左右边缘波束的入射几何，从而产生非对称覆盖宽度。"),
            ("Q2", "任意测线方向覆盖宽度", "survey", "测线方向只通过坡面法向投影改变有效横向坡度。"),
            ("Q3", "规则坡面最短全覆盖测线", "survey", "测线方向与间距共同决定覆盖完整性和总航程。"),
            ("Q4", "实测海床自适应布线", "survey", "局部水深和坡度驱动自适应条带宽度，需联合抑制漏测和过度重叠。"),
        ],
    },
    "2024-B": {
        "run": "pr7-2024b-full-replay-20260717",
        "profile": "evaluation",
        "material": "2024_B",
        "subproblems": [
            ("Q1", "最少抽样接收方案", "sampling", "二项抽样的尾概率可同时控制拒收和接收两类风险。"),
            ("Q2", "两部件生产决策", "decision", "检测、装配、调换与拆解决策共同决定单位产品期望利润。"),
            ("Q3", "多工序多零件决策", "decision", "装配树上的局部缺陷会沿工序传播，应联合优化检测与拆解策略。"),
            ("Q4", "抽样不确定性下重决策", "decision", "次品率估计误差会改变最优策略，稳健决策应覆盖置信区间。"),
        ],
    },
    "2024-C": {
        "run": "pr7-2024c-full-replay-20260717",
        "profile": "engineering_optimization",
        "material": "2024_C",
        "subproblems": [
            ("Q1", "稳定参数多年种植", "crop", "地块容量、适种性、轮作和三年豆类约束决定可行种植组合。"),
            ("Q2", "不确定参数稳健种植", "crop", "销量、产量、成本和价格扰动要求在收益与下行风险之间权衡。"),
            ("Q3", "相关性与替代互补", "crop", "作物间替代互补及价格销量相关性会改变组合分散收益。"),
        ],
    },
    "2024-D": {
        "run": "pr7-2024d-full-replay-20260717",
        "profile": "general",
        "material": "2024_D",
        "subproblems": [
            ("Q1", "无深度误差单弹最优投放", "depth_charge", "水平定位误差与潜艇几何和杀伤半径卷积后决定单弹命中概率。"),
            ("Q2", "三维定位误差单弹定深", "depth_charge", "截尾深度分布与水平定位分布共同决定最佳定深引信深度。"),
            ("Q3", "九弹阵列联合命中", "depth_charge", "阵列间距在单弹覆盖和多弹命中事件相关性之间形成权衡。"),
        ],
    },
}


ROUTE_DESIGNS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "prediction": (
        ("线性趋势基线", "linear_regression", "普通最小二乘拟合并外推目标点"),
        ("二次响应面主路线", "polynomial_response_surface", "解三阶正规方程并计算逐点相对误差"),
        ("指数衰减备选", "exponential_decay", "对平移响应取对数后拟合指数衰减曲线"),
    ),
    "survey": (
        ("等距平行测线基线", "parallel_geometry", "按固定 15% 重叠率解析计算等距测线"),
        ("航向间距联合搜索", "discrete_network_optimization", "枚举航向和重叠率并最小化含覆盖惩罚的总航程"),
        ("水深分带自适应备选", "adaptive_geometry", "按水深分带调整条带宽度并比较多组方向"),
    ),
    "sampling": (
        ("正态近似定样基线", "normal_approximation", "用正态近似给出固定样本量拒收阈值"),
        ("精确二项最小样本", "exact_binomial_search", "枚举样本量和阈值并校验两类尾概率"),
        ("序贯似然边界备选", "sequential_likelihood", "以序贯似然边界的保守代理减少平均抽样量"),
    ),
    "decision": (
        ("不检测策略基线", "fixed_policy", "直接计算无检测无拆解策略的期望利润"),
        ("完整二元策略枚举", "binary_policy_optimization", "枚举检测和拆解决策并最大化多情形平均利润"),
        ("最坏情形稳健备选", "robust_maximin", "在次品率上界扰动下最大化最坏期望利润"),
    ),
    "crop": (
        ("单期贪心收益基线", "greedy_allocation", "按单位收益排序形成容量可行的单期分配"),
        ("轮作约束动态分配", "rotation_dynamic_programming", "联合容量和三年豆类约束进行离散动态分配"),
        ("风险惩罚稳健备选", "robust_portfolio", "按下行风险惩罚后的收益构造分散种植组合"),
    ),
    "depth_charge": (
        ("中心投放解析基线", "closed_form_probability", "以正态分布函数计算中心投放近似命中率"),
        ("确定性网格积分主路线", "grid_quadrature_optimization", "联合枚举落点、定深和阵列间距并比较概率"),
        ("低差异稳健搜索备选", "low_discrepancy_simulation", "用确定性低差异点覆盖连续投放参数空间"),
    ),
}


BASE_CASES = [
    {"p1": 0.10, "c1": 4, "inspect1": 2, "p2": 0.10, "c2": 18, "inspect2": 3, "pf": 0.10, "assembly": 6, "inspect_final": 3, "sale_price": 56, "replacement_loss": 6, "disassembly": 5},
    {"p1": 0.20, "c1": 4, "inspect1": 2, "p2": 0.20, "c2": 18, "inspect2": 3, "pf": 0.20, "assembly": 6, "inspect_final": 3, "sale_price": 56, "replacement_loss": 6, "disassembly": 5},
    {"p1": 0.10, "c1": 4, "inspect1": 2, "p2": 0.10, "c2": 18, "inspect2": 3, "pf": 0.10, "assembly": 6, "inspect_final": 3, "sale_price": 56, "replacement_loss": 30, "disassembly": 5},
    {"p1": 0.20, "c1": 4, "inspect1": 1, "p2": 0.20, "c2": 18, "inspect2": 1, "pf": 0.20, "assembly": 6, "inspect_final": 2, "sale_price": 56, "replacement_loss": 30, "disassembly": 5},
    {"p1": 0.10, "c1": 4, "inspect1": 8, "p2": 0.20, "c2": 18, "inspect2": 1, "pf": 0.10, "assembly": 6, "inspect_final": 2, "sale_price": 56, "replacement_loss": 10, "disassembly": 5},
    {"p1": 0.05, "c1": 4, "inspect1": 2, "p2": 0.05, "c2": 18, "inspect2": 3, "pf": 0.05, "assembly": 6, "inspect_final": 3, "sale_price": 56, "replacement_loss": 10, "disassembly": 40},
]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    head = result.stdout.strip()
    if result.returncode != 0 or len(head) != 40:
        raise RuntimeError("无法取得完整 Git HEAD")
    return head


def _route_config(problem_id: str, subproblem_id: str, category: str) -> dict[str, Any]:
    config: dict[str, Any] = {"problem_id": problem_id, "subproblem_id": subproblem_id, "category": category}
    if category == "prediction":
        xs = [float(index) for index in range(11)]
        curvature = {"Q1": 0.025, "Q2": 0.018, "Q3": 0.032}[subproblem_id]
        config.update({"x": xs, "y": [12.6 - 0.08 * x - curvature * x * x for x in xs], "target_x": 8.5})
    elif category == "survey":
        settings = {
            "Q1": (1600.0, 1000.0, 70.0, 1.5),
            "Q2": (2.1 * 1852, 1852.0, 120.0, 1.5),
            "Q3": (4 * 1852.0, 2 * 1852.0, 110.0, 1.5),
            "Q4": (4 * 1852.0, 5 * 1852.0, 100.0, 3.0),
        }
        width, length, depth, slope = settings[subproblem_id]
        config.update({"area_width_m": width, "area_length_m": length, "depth_m": depth, "slope_deg": slope, "opening_deg": 120.0})
    elif category == "sampling":
        config.update({"nominal_defect_rate": 0.10})
    elif category == "decision":
        cases = BASE_CASES if subproblem_id in {"Q2", "Q4"} else [
            {**BASE_CASES[2], "c1": 42.0, "c2": 38.0, "assembly": 32.0, "sale_price": 200.0, "replacement_loss": 40.0, "disassembly": 10.0}
        ]
        config.update({"cases": cases, "uncertainty": 0.05 if subproblem_id == "Q4" else 0.03})
    elif category == "crop":
        config.update({
            "land_units": 34,
            "crops": [
                {"name": "wheat", "profit": 8.0, "risk": 1.0, "legume": False},
                {"name": "corn", "profit": 8.5, "risk": 1.4, "legume": False},
                {"name": "soybean", "profit": 6.8, "risk": 0.8, "legume": True},
                {"name": "vegetable", "profit": 10.2, "risk": 2.8, "legume": False},
            ],
        })
    elif category == "depth_charge":
        config.update({
            "length": 100.0,
            "width": 20.0,
            "height": 25.0,
            "radius": 20.0,
            "sigma_xy": 120.0,
            "h0": 150.0,
            "sigma_z": 1e-6 if subproblem_id == "Q1" else 40.0,
            "minimum_depth": 120.0,
            "bombs": 9 if subproblem_id == "Q3" else 1,
        })
    return config


def _adapter_report(run_id: str) -> dict[str, Any]:
    requirements = _load(ROOT / "runtime_contracts/upstream_requirements/production_requirements_v1.json")
    mapping_registry = _load(ROOT / "runtime_contracts/upstream_requirements/upstream_requirement_mapping_v1.json")
    mappings = {item["mapping_id"]: item for item in mapping_registry["mappings"]}
    applications = []
    for requirement in requirements["requirements"]:
        mapping = mappings[requirement["mapping_id"]]
        applications.append({
            "requirement_id": requirement["requirement_id"],
            "mapping_id": requirement["mapping_id"],
            "strength": requirement["strength"],
            "applicability": "applicable",
            "target_contracts": mapping["target_contracts"],
            "evidence_requests": mapping["evidence_requests"],
            "diagnostics": ["Adapter 仅提出证据请求，最终判断由本仓 Gate 和 Validator 完成。"],
            "rationale": "该生产要求直接适用于旧题 full_replay 的路线、执行或正式结果证据。",
        })
    return {
        "schema_version": "competition_production_adapter_report_v1",
        "adapter_id": "plugin_competition_production_v1",
        "run_id": run_id,
        "source_commit": "be9c59c1aaa13c3dcb74452ea5cae11dada27589",
        "status": "advisory_only",
        "authority": {"generate_results": False, "modify_paper": False, "decide_gate_pass": False, "advance_stage": False},
        "applications": applications,
    }


def _route_entry(category: str, route_index: int, constraint_id: str) -> dict[str, Any]:
    route_id, role = ROUTES[route_index]
    name, family, algorithm = ROUTE_DESIGNS[category][route_index]
    return {
        "route_id": route_id,
        "role": role,
        "name": name,
        "structural_family": family,
        "rationale": f"以 {family} 独立求解并与另外两类结构路线比较，避免单一模型偶然性。",
        "model": family,
        "assumptions": ["仅使用题面和冻结输入中的参数。", "数值过程固定 seed=0 且禁止网络访问。"],
        "decision_variables": [{"name": "route_solution", "definition": "该路线的核心参数或决策向量", "unit": None, "source": "冻结路线输入"}],
        "objectives": ["在满足题面硬约束后优化该子问题的正式目标值。"],
        "constraint_ids": [constraint_id],
        "data_requirements": ["problem/route_input.json 中的冻结参数与样本"],
        "algorithm": algorithm,
        "expected_outputs": ["objective", "solver_status", "路线特有参数和约束检查"],
        "validation_requirements": ["独立 Sandboxie 执行证明", "Formal Result 哈希闭包", "负控测试通过"],
        "failure_conditions": ["输入哈希漂移", "执行未完成", "硬约束检查失败", "检测到数据泄漏"],
    }


def _model_route(manifest: Mapping[str, Any], problem: Mapping[str, Any]) -> dict[str, Any]:
    subproblems = []
    for subproblem_id, title, category, hypothesis in problem["subproblems"]:
        constraint_id = f"BC-{subproblem_id}-OFFICIAL"
        subproblems.append({
            "subproblem_id": subproblem_id,
            "task_type": category,
            "inputs": [{"name": "official_problem_parameters", "definition": f"{title} 的冻结题面参数与数值样本", "unit": None, "source": str(manifest["material_manifest"])}],
            "outputs": [{"name": "formal_objective", "definition": "由可信 Collector 派生的路线正式目标值", "unit": None, "source": "Formal Result"}],
            "mechanism_hypothesis": {"statement": hypothesis, "rationale": "假设直接对应官方题面给出的物理、统计或业务机制，并由三条结构路线交叉检验。", "falsification_checks": ["比较三路线目标与稳定性", "回代题面硬约束", "检查输入和执行证明哈希"]},
            "business_constraints": [{"constraint_id": constraint_id, "statement": f"{title} 必须满足官方题面全部物理、统计或业务边界。", "strength": "hard", "source_ref": f"official_materials/{problem['material']}/material_manifest.json", "verification_method": "独立 Validator 对 Formal Result 和可执行性报告逐项回代。"}],
            "routes": [_route_entry(category, index, constraint_id) for index in range(3)],
            "structural_difference": {"primary_route_id": "R-PRIMARY", "alternative_route_id": "R-ALT", "differs_in": ["mechanism", "algorithm_family", "decision_representation"], "explanation": "主路线采用确定性联合优化或精确拟合，备选路线采用稳健、指数、分带或低差异结构，不共享核心算法族。"},
            "comparison_metrics": ["正式目标值", "可行性", "执行时间", "数值稳定性"],
        })
    return {
        "schema_version": "3.0.0",
        "artifact_type": "model_route_v3",
        "run_id": manifest["run_id"],
        "problem_id": manifest["problem_id"],
        "profile": manifest["profile"],
        "runtime_version": manifest["runtime_version"],
        "runtime_pack_sha256": manifest["runtime_pack_sha256"],
        "lifecycle": "review_ready",
        "subproblems": subproblems,
        "human_decisions_required": ["Gate 5 人工评审需确认结论边界与提交稿准入。"],
    }


def _child_manifest(parent: Mapping[str, Any], child_run_id: str) -> dict[str, Any]:
    fields = (
        "problem_id", "profile", "runtime_version", "runtime_pack_sha256", "formal_result_policy",
        "execution_contract_version", "formal_result_contract_version", "canonicalization_version",
        "gate_artifact_contract_version",
    )
    return {"manifest_version": "2.0.0", "run_id": child_run_id, **{field: parent[field] for field in fields}}


def _execution_spec(child: Mapping[str, Any], input_path: Path, task_id: str, approved_at: str) -> dict[str, Any]:
    identity_fields = (
        "run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256", "formal_result_policy",
        "execution_contract_version", "formal_result_contract_version", "canonicalization_version",
        "gate_artifact_contract_version",
    )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "execution_spec",
        **{field: child[field] for field in identity_fields},
        "execution_mode": "trusted_local",
        "declared_workspace": "workspace",
        "network_access": False,
        "declared_writable_paths": ["workspace/output"],
        "approved_by": "pr7-route-approval",
        "approved_at": approved_at,
        "contract_notes": ["候选执行和可信 Sandboxie 执行必须使用同一冻结输入和代码哈希。"],
        "tasks": [{
            "task_id": task_id,
            "runner": "python",
            "entrypoint": "code/solve.py",
            "entrypoint_arg_index": 1,
            "argv": ["python", "code/solve.py", "--input", "input/route_input.json"],
            "working_directory": "workspace",
            "inputs": [{"path": "problem/route_input.json", "sha256": file_sha256(input_path)}],
            "required_outputs": [{"path": "workspace/output/result.json", "media_type": "application/json"}],
            "depends_on": [],
            "timeout_seconds": 120,
            "seed_policy": {"deterministic_expected": True, "seeds": [0]},
            "acceptance_checks": [{"check_id": "result-json", "kind": "file_exists", "expectation": "output/result.json"}],
            "fallback": "emit_blocker",
        }],
    }


def prepare_problem(problem_id: str, problem: Mapping[str, Any], environment_report: Path) -> dict[str, Any]:
    run_root = ROOT / "runs" / str(problem["run"])
    manifest = _load(run_root / "run_manifest.json")
    if manifest["profile"] != problem["profile"]:
        raise ValueError(f"{problem_id} Profile 与 Campaign 设计不一致")
    route_root = run_root / "route_runs"
    if route_root.exists():
        raise ValueError(f"{problem_id} 已存在 route_runs，拒绝覆盖")
    staging_root = Path(tempfile.mkdtemp(prefix=".route_runs_stage_", dir=run_root))
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    _write(run_root / "competition_production_adapter_report.json", _adapter_report(str(manifest["run_id"])))
    model = _model_route(manifest, problem)
    validate_artifact(model, context="full_replay")
    _write(run_root / "model_route_v3.json", model)
    _write(run_root / "full_replay_session.json", {"started_at": started_at, "source_control_commit": _git_head()})
    prepared = 0
    mechanism_by_category = {"prediction": "nonlinear", "survey": "network_optimization", "sampling": "heuristic", "decision": "mip", "crop": "mip", "depth_charge": "nonlinear"}
    for subproblem_id, _title, category, _hypothesis in problem["subproblems"]:
        for route_id, role in ROUTES:
            child_run_id = f"{manifest['run_id']}-{subproblem_id.lower()}-{route_id.removeprefix('R-').lower()}"
            child_root = staging_root / subproblem_id / route_id
            child = _child_manifest(manifest, child_run_id)
            _write(child_root / "run_manifest.json", child)
            config = _route_config(problem_id, subproblem_id, category)
            config.update({"route_id": route_id, "role": role})
            input_path = child_root / "problem" / "route_input.json"
            _write(input_path, config)
            code_path = child_root / "workspace" / "code" / "solve.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "scripts" / "full_replay_route_solver.py", code_path)
            task_id = f"{subproblem_id}_{route_id.removeprefix('R-')}"
            _write(child_root / "execution_spec.json", _execution_spec(child, input_path, task_id, started_at))
            initialize_formal_result(
                child_root,
                f"formal-{subproblem_id.lower()}-{route_id.removeprefix('R-').lower()}",
                environment_report,
                mechanism=mechanism_by_category[category],
                validator_id="pr7-formal-independent-validator",
            )
            prepared += 1
    staging_root.replace(route_root)
    return {"problem_id": problem_id, "run_id": manifest["run_id"], "subproblem_count": len(problem["subproblems"]), "route_run_count": prepared}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-report", type=Path, required=True)
    parser.add_argument("--problem", choices=tuple(PROBLEMS), action="append")
    args = parser.parse_args()
    selected = args.problem or list(PROBLEMS)
    try:
        results = [prepare_problem(problem_id, PROBLEMS[problem_id], args.environment_report) for problem_id in selected]
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps({"status": "prepared", "problems": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
