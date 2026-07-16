"""2024-B 生产质量决策的 Gate 3 独立验证器。

不导入主求解器；只读取父进程绑定的候选结果与执行记录，并以独立 Bellman
线性方程复算问题 3 的候选策略目标。题面 PDF 在输入清单中绑定，数值常数在本文件
按题面表 2 明确重建，以避免复用主程序的中间计算结果。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


VALIDATOR_PATH = "validators/quality_decision_2024b/validate.py"
TOLERANCE = 1e-8
PARTS = (
    (0.10, 2.0, 1.0), (0.10, 8.0, 1.0), (0.10, 12.0, 2.0),
    (0.10, 2.0, 1.0), (0.10, 8.0, 1.0), (0.10, 12.0, 2.0),
    (0.10, 8.0, 1.0), (0.10, 12.0, 2.0),
)
GROUPS = ((0, 1, 2), (3, 4, 5), (6, 7))


@dataclass(frozen=True)
class Component:
    """独立复算时进入最终装配层的等效组件。"""

    defect_rate: float
    purchase_cost: float
    inspection_cost: float


def sha256(path: Path) -> str:
    """计算文件哈希，拒绝使用未由父进程绑定的内容。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    """读取单个 JSON 对象。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return value


def grouped_inputs(manifest_path: Path) -> dict[str, Path]:
    """验证输入清单哈希，并为每个角色返回唯一文件。"""
    manifest = load_object(manifest_path)
    run_root = manifest_path.resolve().parents[1]
    grouped: dict[str, Path] = {}
    for item in manifest.get("artifacts", []):
        if not isinstance(item, Mapping):
            raise ValueError("输入清单包含非法工件")
        role = str(item["role"])
        path = (run_root / str(item["path"])).resolve()
        if not path.is_relative_to(run_root) or not path.is_file():
            raise ValueError(f"输入路径非法：{item['path']}")
        if sha256(path) != item["sha256"]:
            raise ValueError(f"输入哈希不匹配：{item['path']}")
        if role in grouped:
            raise ValueError(f"输入角色必须唯一：{role}")
        grouped[role] = path
    required = {"problem_data", "candidate_solution", "model_parameters", "solver_log"}
    if set(grouped) != required:
        raise ValueError(f"输入角色集合不匹配：{sorted(grouped)}")
    return grouped


def solve_linear(matrix: list[list[float]], right: list[float]) -> list[float] | None:
    """以带主元高斯消元独立求解状态价值方程。"""
    size = len(right)
    augmented = [row[:] + [right[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            ratio = augmented[row][column]
            augmented[row] = [
                value - ratio * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[index][-1] for index in range(size)]


def evaluate_policy(
    components: Sequence[Component],
    inspect_components: Sequence[bool],
    inspect_product: bool,
    disassemble: bool,
) -> float | None:
    """按题面最终装配成本独立计算续生产期望净收益。"""
    state_count = 1 << len(components)
    initial_probabilities: list[float] = []
    for state in range(state_count):
        probability = 1.0
        for index, component in enumerate(components):
            probability *= 1.0 - component.defect_rate if state & (1 << index) else component.defect_rate
        initial_probabilities.append(probability)
    matrix = [[0.0] * state_count for _ in range(state_count)]
    right = [0.0] * state_count
    initial_cost = sum(component.purchase_cost for component in components)
    for state in range(state_count):
        after = state
        cost = 0.0
        for index, component in enumerate(components):
            if not inspect_components[index]:
                continue
            cost += component.inspection_cost
            if not after & (1 << index):
                cost += (component.purchase_cost + component.inspection_cost) / (1.0 - component.defect_rate)
                after |= 1 << index
        good = 0.90 if after == state_count - 1 else 0.0
        bad = 1.0 - good
        right[state] = -cost - 8.0 - (6.0 if inspect_product else 0.0) + good * 200.0 - bad * ((0.0 if inspect_product else 40.0) + (10.0 if disassemble else 0.0))
        matrix[state][state] = 1.0
        if disassemble:
            matrix[state][after] -= bad
        else:
            for target, probability in enumerate(initial_probabilities):
                matrix[state][target] -= bad * probability
            right[state] -= bad * initial_cost
    values = solve_linear(matrix, right)
    if values is None:
        return None
    return sum(probability * value for probability, value in zip(initial_probabilities, values)) - initial_cost


def q3_components(policy: Mapping[str, Any]) -> tuple[list[Component], float]:
    """由候选策略和题面常数重建三个半成品的等效参数及结构残差。"""
    inspect_parts = policy.get("inspect_parts")
    inspect_semis = policy.get("inspect_semiproducts")
    dismantle_semis = policy.get("disassemble_defective_semiproducts")
    if not isinstance(inspect_parts, list) or not isinstance(inspect_semis, list) or not isinstance(dismantle_semis, list):
        raise ValueError("问题 3 策略缺少布尔决策数组")
    residual = float(abs(len(inspect_parts) - 8) + abs(len(inspect_semis) - 3) + abs(len(dismantle_semis) - 3))
    if residual > 0:
        return [], residual
    if any(not isinstance(value, bool) for value in [*inspect_parts, *inspect_semis, *dismantle_semis]):
        return [], 1.0
    components: list[Component] = []
    for semi_index, group in enumerate(GROUPS):
        initial_cost = 0.0
        child_good = 1.0
        all_checked = True
        for part_index in group:
            rate, purchase, inspection = PARTS[part_index]
            checked = inspect_parts[part_index]
            all_checked = all_checked and checked
            if checked:
                initial_cost += (purchase + inspection) / (1.0 - rate)
            else:
                initial_cost += purchase
                child_good *= 1.0 - rate
        semi_good = child_good * 0.90
        if dismantle_semis[semi_index]:
            if not inspect_semis[semi_index] or not all_checked:
                residual = max(residual, 1.0)
                continue
            initial_trial = initial_cost + 8.0 + 4.0
            repeat_trial = sum(PARTS[index][2] for index in group) + 8.0 + 4.0 + 6.0
            components.append(Component(0.0, initial_trial + 0.10 / 0.90 * repeat_trial, 0.0))
        else:
            components.append(Component(1.0 - semi_good, initial_cost + 8.0, 4.0))
    return components, residual


def observation(name: str, value: float) -> dict[str, object]:
    """生成符合 Gate 3 报告 Schema 的数值观察。"""
    if not math.isfinite(value):
        raise ValueError(f"观察值非有限数：{name}")
    return {"name": name, "value": value}


def build_report(manifest_path: Path, report_path: Path) -> dict[str, object]:
    """对受控候选结果执行五项工程优化 Gate 3 检查。"""
    paths = grouped_inputs(manifest_path)
    result = load_object(paths["candidate_solution"])
    model_contract = load_object(paths["model_parameters"])
    execution_record = load_object(paths["solver_log"])
    q3 = result.get("q3")
    if not isinstance(q3, Mapping) or not isinstance(q3.get("best"), Mapping):
        raise ValueError("候选结果缺少问题 3 最优策略")
    best = q3["best"]
    policy = best.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("问题 3 最优策略格式错误")
    components, residual = q3_components(policy)
    recomputed = evaluate_policy(
        components,
        list(policy.get("inspect_semiproducts", [])),
        bool(policy.get("inspect_final_product")),
        bool(policy.get("disassemble_defective_final_product")),
    ) if len(components) == 3 and residual == 0.0 else None
    reported = best.get("expected_net_value")
    objective = result.get("objective")
    if not isinstance(reported, (int, float)) or not isinstance(objective, (int, float)) or recomputed is None:
        raise ValueError("问题 3 目标不可独立复算")
    error = abs(float(reported) - recomputed)
    candidate_count = q3.get("candidate_policy_count")
    consistency = float(
        error <= TOLERANCE
        and abs(float(objective) - float(reported)) <= TOLERANCE
        and candidate_count == 12960
    )
    status_ok = all(
        (
            execution_record.get("exit_code") == 0,
            execution_record.get("code_unchanged") is True,
            execution_record.get("input_unchanged") is True,
            execution_record.get("output_set_exact") is True,
            result.get("solver_status") == "feasible",
            model_contract.get("contract_status") == "planned",
        )
    )
    checks = [
        {
            "check_id": "objective_recomputation",
            "observations": [
                observation("reported_objective", float(reported)),
                observation("recomputed_objective", recomputed),
                observation("absolute_error", error),
            ],
        },
        {
            "check_id": "constraint_residual",
            "observations": [observation("max_constraint_residual", residual)],
        },
        {
            "check_id": "decision_output_consistency",
            "observations": [observation("decision_output_match", consistency)],
        },
        {
            "check_id": "variable_domain",
            "observations": [observation("max_domain_violation", residual)],
        },
        {
            "check_id": "solver_status",
            "observations": [observation("solver_exit_code", 0.0 if status_ok else 1.0)],
        },
    ]
    report = {
        "validator_path": VALIDATOR_PATH,
        "validator_sha256": sha256(Path(__file__).resolve()),
        "input_manifest_sha256": sha256(manifest_path),
        "checks": checks,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """解析 Gate 3 父进程固定传入的输入与报告路径。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    build_report(Path(args.input_manifest), Path(args.report))
    print("2024-B Gate 3 independent validator completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
