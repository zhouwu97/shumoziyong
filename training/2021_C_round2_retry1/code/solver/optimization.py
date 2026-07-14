"""本轮问题2至问题4的可审计 MILP 求解器。

每个模型只使用本轮 ``common`` 中由官方材料计算出的参数；转运分配与订货量导出
均保留到完整精度，最终结果再交给独立检查器复算。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from common.common import DEMAND_BASE, HORIZON, TOLERANCE, TRANSPORTER_CAPACITY, now_iso


@dataclass
class MilpRun:
    """保存一个 HiGHS 调用的解与可审计状态。"""

    x: np.ndarray
    status: dict[str, Any]


class ConstraintBuilder:
    """以稀疏三元组方式搭建线性约束，避免构造稠密大矩阵。"""

    def __init__(self, variable_count: int) -> None:
        self.variable_count = variable_count
        self.rows: list[int] = []
        self.columns: list[int] = []
        self.values: list[float] = []
        self.lower: list[float] = []
        self.upper: list[float] = []
        self._row = 0

    def add(self, indices: np.ndarray, values: np.ndarray, lower: float, upper: float) -> None:
        self.rows.extend([self._row] * len(indices))
        self.columns.extend(indices.astype(int).tolist())
        self.values.extend(values.astype(float).tolist())
        self.lower.append(float(lower))
        self.upper.append(float(upper))
        self._row += 1

    def linear_constraint(self) -> LinearConstraint:
        matrix = coo_matrix(
            (self.values, (self.rows, self.columns)),
            shape=(self._row, self.variable_count),
        ).tocsr()
        return LinearConstraint(matrix, np.array(self.lower), np.array(self.upper))


def _status(result: Any, start: float, objective_name: str, time_limit_seconds: float) -> dict[str, Any]:
    """抽取 SciPy/HiGHS 状态，避免把求解器内部对象写入结果。"""
    return {
        "solver": "SciPy HiGHS MILP",
        "solver_version": "SciPy 1.17.0 bundled runtime",
        "model_type": "mixed_integer_linear_program",
        "objective_name": objective_name,
        "start_time": now_iso(),
        "end_time": now_iso(),
        "runtime_seconds": time.perf_counter() - start,
        "time_limit_seconds": time_limit_seconds,
        "status_code": int(result.status),
        "status_text": str(result.message),
        "feasible": bool(result.x is not None),
        "optimality_proven": bool(result.success),
        "mip_gap": float(getattr(result, "mip_gap", np.nan)) if getattr(result, "mip_gap", None) is not None else None,
        "node_count": int(getattr(result, "mip_node_count", 0) or 0),
        "solver_objective": float(result.fun) if result.fun is not None else None,
    }


def _solve(
    objective: np.ndarray,
    builder: ConstraintBuilder,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    integrality: np.ndarray,
    objective_name: str,
    time_limit_seconds: float = 300.0,
) -> MilpRun:
    """运行一次有300秒上限的 HiGHS MILP，并在无可行解时显式报错。"""
    start = time.perf_counter()
    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=builder.linear_constraint(),
        options={"time_limit": time_limit_seconds, "mip_rel_gap": 0.0},
    )
    status = _status(result, start, objective_name, time_limit_seconds)
    if result.x is None:
        raise RuntimeError(f"{objective_name} 未得到可行解: {status['status_text']}")
    return MilpRun(np.maximum(result.x, 0.0), status)


def _indices(supplier_count: int, transporter_count: int) -> tuple[np.ndarray, np.ndarray, int]:
    flow = np.arange(supplier_count * transporter_count, dtype=int).reshape(supplier_count, transporter_count)
    assign = flow + supplier_count * transporter_count
    return flow, assign, supplier_count * transporter_count * 2


def _base_builder(
    data: dict[str, Any], candidate_indices: np.ndarray, loss_multiplier: float = 1.0,
    enforce_single_carrier: bool = True,
) -> tuple[ConstraintBuilder, np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """建立供应能力、转运能力与单一转运商的共同硬约束。"""
    capacities = data["regular_order_capacity"][candidate_indices].astype(float)
    raw_per_product = data["raw_per_product"][candidate_indices].astype(float)
    unit_cost = data["unit_cost"][candidate_indices].astype(float)
    losses = np.clip(data["loss_mean"].astype(float) * loss_multiplier, 0.0, 0.99)
    supplier_count = len(candidate_indices)
    transporter_count = len(losses)
    flow, assign, full_variable_count = _indices(supplier_count, transporter_count)
    flow_count = supplier_count * transporter_count
    variable_count = full_variable_count if enforce_single_carrier else flow_count
    builder = ConstraintBuilder(variable_count)

    # 每家供应商一周的预计实际供货不能超过历史估计的常规供货上限。
    for i in range(supplier_count):
        builder.add(flow[i], np.ones(transporter_count), -np.inf, capacities[i])
    # 每家转运商每周最多承运 6000 立方米原料。
    for j in range(transporter_count):
        builder.add(flow[:, j], np.ones(supplier_count), -np.inf, TRANSPORTER_CAPACITY)
    if enforce_single_carrier:
        # 问题2把“尽量”落实为可执行硬约束；问题3/4只将其作为披露指标。
        for i in range(supplier_count):
            builder.add(assign[i], np.ones(transporter_count), -np.inf, 1.0)
            for j in range(transporter_count):
                builder.add(
                    np.array([flow[i, j], assign[i, j]]),
                    np.array([1.0, -capacities[i]]),
                    -np.inf,
                    0.0,
                )
        lower = np.zeros(variable_count, dtype=float)
        upper = np.concatenate(
            [
                np.repeat(capacities, transporter_count),
                np.ones(flow_count, dtype=float),
            ]
        )
        integrality = np.concatenate(
            [np.zeros(flow_count, dtype=int), np.ones(flow_count, dtype=int)]
        )
    else:
        lower = np.zeros(variable_count, dtype=float)
        upper = np.repeat(capacities, transporter_count)
        integrality = np.zeros(variable_count, dtype=int)
    product_coefficient = np.array(
        [
            (1.0 - losses[j]) / raw_per_product[i]
            for i in range(supplier_count)
            for j in range(transporter_count)
        ],
        dtype=float,
    )
    loss_coefficient = np.array(
        [losses[j] for _i in range(supplier_count) for j in range(transporter_count)], dtype=float
    )
    raw_coefficient = np.ones(supplier_count * transporter_count, dtype=float)
    cost_coefficient = np.repeat(unit_cost, transporter_count)
    metadata = {
        "flow": flow,
        "assign": assign,
        "capacities": capacities,
        "raw_per_product": raw_per_product,
        "losses": losses,
        "product_coefficient": product_coefficient,
        "loss_coefficient": loss_coefficient,
        "raw_coefficient": raw_coefficient,
        "cost_coefficient": cost_coefficient,
        "single_carrier_hard": np.array([enforce_single_carrier]),
    }
    return builder, lower, upper, integrality, metadata


def _with_constraint(
    base_builder: ConstraintBuilder,
    indices: np.ndarray,
    values: np.ndarray,
    lower: float,
    upper: float,
) -> ConstraintBuilder:
    """复制当前约束并追加一行，服务词典序目标的后续阶段。"""
    clone = ConstraintBuilder(base_builder.variable_count)
    clone.rows = list(base_builder.rows)
    clone.columns = list(base_builder.columns)
    clone.values = list(base_builder.values)
    clone.lower = list(base_builder.lower)
    clone.upper = list(base_builder.upper)
    clone._row = base_builder._row
    clone.add(indices, values, lower, upper)
    return clone


def _decode_solution(
    data: dict[str, Any],
    candidate_indices: np.ndarray,
    run: MilpRun,
    metadata: dict[str, np.ndarray],
    demand: float,
    part: str,
    selection_method: str,
) -> dict[str, Any]:
    """将单周最优流量扩展为题目要求的24周方案和库存轨迹。"""
    supplier_count = len(candidate_indices)
    transporter_count = len(data["transporter_ids"])
    flow = run.x[metadata["flow"].reshape(-1)].reshape(supplier_count, transporter_count)
    shipment_one_week = np.zeros((len(data["supplier_ids"]), transporter_count), dtype=float)
    shipment_one_week[candidate_indices, :] = flow
    supply_one_week = shipment_one_week.sum(axis=1)
    alpha = data["order_response_ratio"]
    order_one_week = np.divide(
        supply_one_week,
        alpha,
        out=np.zeros_like(supply_one_week),
        where=alpha > TOLERANCE,
    )
    arrival_raw_one_week = (shipment_one_week * (1.0 - metadata["losses"])[None, :]).sum(axis=1)
    arrival_product = float(np.sum(arrival_raw_one_week / data["raw_per_product"]))
    losses_by_transporter = (shipment_one_week * metadata["losses"][None, :]).sum(axis=0)
    active = [
        data["supplier_ids"][index]
        for index in range(len(data["supplier_ids"]))
        if supply_one_week[index] > TOLERANCE
    ]
    inventory = [2.0 * demand]
    for _week in range(HORIZON):
        inventory.append(inventory[-1] + arrival_product - demand)
    return {
        "problem_part": part,
        "demand_product_m3_per_week": demand,
        "selection_method": selection_method,
        "selected_supplier_ids": active,
        "active_supplier_ids": active,
        "candidate_supplier_ids": [data["supplier_ids"][index] for index in candidate_indices],
        "supplier_ids": data["supplier_ids"],
        "material_types": data["material_types"],
        "transporter_ids": data["transporter_ids"],
        "orders_raw_m3": np.repeat(order_one_week[:, None], HORIZON, axis=1).tolist(),
        "expected_supply_raw_m3": np.repeat(supply_one_week[:, None], HORIZON, axis=1).tolist(),
        "shipments_raw_m3": np.repeat(shipment_one_week[:, None, :], HORIZON, axis=1).tolist(),
        "arrivals_raw_m3": np.repeat(arrival_raw_one_week[:, None], HORIZON, axis=1).tolist(),
        "arrivals_product_equivalent_m3": [arrival_product] * HORIZON,
        "losses_by_transporter_raw_m3": np.repeat(losses_by_transporter[None, :], HORIZON, axis=0).tolist(),
        "inventory_product_equivalent_m3": inventory,
        "model_metadata": {
            "planned_loss_rate_by_transporter": metadata["losses"].tolist(),
            "regular_order_capacity_raw_m3": data["regular_order_capacity"].tolist(),
            "order_response_ratio": data["order_response_ratio"].tolist(),
            "single_carrier_hard": bool(metadata["single_carrier_hard"][0]),
        },
    }


def _objective_values(solution: dict[str, Any], data: dict[str, Any]) -> dict[str, float]:
    supply = np.asarray(solution["expected_supply_raw_m3"], dtype=float)
    shipments = np.asarray(solution["shipments_raw_m3"], dtype=float)
    cost = float(np.sum(supply * data["unit_cost"][:, None]))
    loss = float(np.sum(shipments * data["loss_mean"][None, None, :]))
    raw = float(supply.sum())
    a_count = float(supply[np.array(data["material_types"]) == "A"].sum())
    c_count = float(supply[np.array(data["material_types"]) == "C"].sum())
    return {
        "purchase_cost_relative": cost,
        "transport_loss_raw_m3": loss,
        "total_expected_supply_raw_m3": raw,
        "a_expected_supply_raw_m3": a_count,
        "c_expected_supply_raw_m3": c_count,
    }


def choose_minimum_supplier_set(data: dict[str, Any], demand: float, loss_multiplier: float = 1.0) -> np.ndarray:
    """按净产品能力从高到低累加，得到满足周需求所需的最少供应商数。

    当每个供应商的选择成本同为1且能力均非负时，该排序累加等价于最小基数覆盖问题的
    精确解；这里使用损耗最小转运商的预测损耗作为筛选阶段的必要条件近似，正式模型再
    用所有转运能力作可行性验证。
    """
    best_loss = float(np.min(np.clip(data["loss_mean"] * loss_multiplier, 0.0, 0.99)))
    ability = data["regular_order_capacity"] * (1.0 - best_loss) / data["raw_per_product"]
    usable = np.flatnonzero(ability > TOLERANCE)
    order = usable[np.argsort(-ability[usable], kind="stable")]
    cumulative = np.cumsum(ability[order])
    position = int(np.searchsorted(cumulative, demand - TOLERANCE))
    if position >= len(order):
        raise RuntimeError("基于常规供货能力无法满足周生产需求")
    return order[: position + 1]


def baseline_problem2(data: dict[str, Any], demand: float = DEMAND_BASE) -> dict[str, Any]:
    """透明基线：按最少能力集合、单位产品采购成本和最低损耗承运商贪心安排。

    它不调用优化器，专门作为正式词典序 MILP 的可解释对照。供应商只分配给一名
    转运商；若其最优承运商剩余能力不足，则该供应商本周不再拆分运输。
    """
    initial_candidates = choose_minimum_supplier_set(data, demand)
    best_loss = float(np.min(data["loss_mean"]))
    ability = data["regular_order_capacity"] * (1.0 - best_loss) / data["raw_per_product"]
    ranked_candidates = np.flatnonzero(ability > TOLERANCE)[np.argsort(-ability[ability > TOLERANCE], kind="stable")]
    candidates = initial_candidates.copy()
    minimum_count = len(initial_candidates)

    def make_greedy_flow(candidate_array: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray, float]:
        _builder, local_lower, _upper, _integrality, local_meta = _base_builder(data, candidate_array, enforce_single_carrier=True)
        transporter_count = len(data["transporter_ids"])
        local_flow = np.zeros((len(candidate_array), transporter_count), dtype=float)
        remaining_product = demand
        remaining_transport = np.full(transporter_count, TRANSPORTER_CAPACITY, dtype=float)
        effective_cost = data["unit_cost"][candidate_array] * data["raw_per_product"][candidate_array] / (1.0 - np.min(local_meta["losses"]))
        supplier_order = np.argsort(effective_cost, kind="stable")
        transport_order = np.argsort(local_meta["losses"], kind="stable")
        for local_index in supplier_order:
            if remaining_product <= TOLERANCE:
                break
            supplier_index = candidate_array[local_index]
            for transporter in transport_order:
                if remaining_transport[transporter] <= TOLERANCE:
                    continue
                needed_raw = remaining_product * data["raw_per_product"][supplier_index] / (1.0 - local_meta["losses"][transporter])
                volume = min(data["regular_order_capacity"][supplier_index], needed_raw, remaining_transport[transporter])
                if volume <= TOLERANCE:
                    continue
                local_flow[local_index, transporter] = volume
                remaining_transport[transporter] -= volume
                remaining_product -= volume * (1.0 - local_meta["losses"][transporter]) / data["raw_per_product"][supplier_index]
                break
        return local_flow, local_meta, local_lower, remaining_product

    flow, meta, lower, remaining_product = make_greedy_flow(candidates)
    for candidate in ranked_candidates:
        if remaining_product <= TOLERANCE:
            break
        if candidate in candidates:
            continue
        candidates = np.append(candidates, candidate)
        flow, meta, lower, remaining_product = make_greedy_flow(candidates)
    if remaining_product > TOLERANCE:
        raise RuntimeError(f"透明基线未能满足周需求，缺口 {remaining_product:.6f}")
    vector = np.zeros(len(lower), dtype=float)
    vector[meta["flow"].reshape(-1)] = flow.reshape(-1)
    pseudo_run = MilpRun(vector, {"solver": "deterministic greedy baseline", "status_text": "feasible"})
    solution = _decode_solution(data, candidates, pseudo_run, meta, demand, "2", "最小能力集合上的成本优先单承运商贪心基线")
    solution["selection_minimum_count"] = int(minimum_count)
    solution["baseline_selected_count"] = int(len(candidates))
    solution["selected_supplier_ids"] = [data["supplier_ids"][index] for index in candidates]
    solution["objective"] = _objective_values(solution, data)
    solution["baseline_limitations"] = [
        "按供应商顺序贪心，未在供应商之间全局平衡采购成本与损耗。",
        "使用历史常规供货上限，不能保证未来每周真实供货。",
    ]
    return solution


def solve_problem2(data: dict[str, Any], demand: float = DEMAND_BASE, loss_multiplier: float = 1.0,
                   cap_multiplier: dict[str, float] | None = None,
                   time_limit_seconds: float = 300.0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """问题2：先最小化供应商数，再在固定集合内词典序最小化采购成本与运输损耗。"""
    adjusted = dict(data)
    capacities = data["regular_order_capacity"].copy()
    if cap_multiplier:
        for supplier_id, multiplier in cap_multiplier.items():
            try:
                index = data["supplier_ids"].index(supplier_id)
            except ValueError:
                continue
            capacities[index] *= multiplier
    adjusted["regular_order_capacity"] = capacities
    candidates = choose_minimum_supplier_set(adjusted, demand, loss_multiplier)
    builder, lower, upper, integrality, meta = _base_builder(adjusted, candidates, loss_multiplier)
    flow_count = len(candidates) * len(data["transporter_ids"])
    flow_indices = np.arange(flow_count)
    stage0 = _with_constraint(builder, flow_indices, meta["product_coefficient"], demand, np.inf)
    cost_objective = np.concatenate([meta["cost_coefficient"], np.zeros(len(lower) - flow_count)])
    cost_run = _solve(cost_objective, stage0, lower, upper, integrality, "问题2采购成本最小化", time_limit_seconds)
    cost_limit = float(cost_run.x[:flow_count] @ meta["cost_coefficient"])
    stage1 = _with_constraint(stage0, flow_indices, meta["cost_coefficient"], -np.inf, cost_limit + TOLERANCE)
    loss_objective = np.concatenate([meta["loss_coefficient"], np.zeros(len(lower) - flow_count)])
    loss_run = _solve(loss_objective, stage1, lower, upper, integrality, "问题2运输损耗最小化", time_limit_seconds)
    solution = _decode_solution(
        adjusted, candidates, loss_run, meta, demand, "2", "最小基数能力覆盖后词典序成本-损耗 MILP"
    )
    solution["selection_minimum_count"] = int(len(candidates))
    solution["selected_supplier_ids"] = [data["supplier_ids"][index] for index in candidates]
    solution["selection_capacity_product_equivalent_m3"] = float(
        np.sum(adjusted["regular_order_capacity"][candidates] * (1.0 - np.min(meta["losses"])) / adjusted["raw_per_product"][candidates])
    )
    solution["objective"] = _objective_values(solution, adjusted)
    return solution, [cost_run.status, loss_run.status]


def solve_problem3(data: dict[str, Any], demand: float = DEMAND_BASE, loss_multiplier: float = 1.0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """问题3：词典序地少用C、少用原料（自然偏向A）、再少损耗。"""
    candidates = np.flatnonzero(data["regular_order_capacity"] > TOLERANCE)
    builder, lower, upper, integrality, meta = _base_builder(
        data, candidates, loss_multiplier, enforce_single_carrier=False
    )
    flow_count = len(candidates) * len(data["transporter_ids"])
    flow_indices = np.arange(flow_count)
    stage0 = _with_constraint(builder, flow_indices, meta["product_coefficient"], demand, np.inf)
    candidate_types = np.array(data["material_types"])[candidates]
    c_objective_flow = np.repeat((candidate_types == "C").astype(float), len(data["transporter_ids"]))
    c_objective = np.concatenate([c_objective_flow, np.zeros(len(lower) - flow_count)])
    c_run = _solve(c_objective, stage0, lower, upper, integrality, "问题3 C类原料最小化")
    c_limit = float(c_run.x[:flow_count] @ c_objective_flow)
    stage1 = _with_constraint(stage0, flow_indices, c_objective_flow, -np.inf, c_limit + TOLERANCE)
    raw_objective = np.concatenate([meta["raw_coefficient"], np.zeros(len(lower) - flow_count)])
    raw_run = _solve(raw_objective, stage1, lower, upper, integrality, "问题3原料运输量最小化")
    raw_limit = float(raw_run.x[:flow_count] @ meta["raw_coefficient"])
    stage2 = _with_constraint(stage1, flow_indices, meta["raw_coefficient"], -np.inf, raw_limit + TOLERANCE)
    loss_objective = np.concatenate([meta["loss_coefficient"], np.zeros(len(lower) - flow_count)])
    loss_run = _solve(loss_objective, stage2, lower, upper, integrality, "问题3运输损耗最小化")
    solution = _decode_solution(data, candidates, loss_run, meta, demand, "3", "C最少-原料量最少-损耗最少的词典序 MILP")
    solution["objective"] = _objective_values(solution, data)
    statuses = [c_run.status, raw_run.status, loss_run.status]
    for status in statuses:
        status["model_type"] = "linear_program_with_soft_single_carrier_indicator"
    return solution, statuses


def solve_problem4(data: dict[str, Any], loss_multiplier: float = 1.0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """问题4：在所有可用供应商与转运能力下最大化可持续周产能。"""
    candidates = np.flatnonzero(data["regular_order_capacity"] > TOLERANCE)
    builder, lower, upper, integrality, meta = _base_builder(
        data, candidates, loss_multiplier, enforce_single_carrier=False
    )
    flow_count = len(candidates) * len(data["transporter_ids"])
    flow_indices = np.arange(flow_count)
    # 最大化到货可生产量等价于最小化其相反数；正系数确保不会无故闲置可用能力。
    objective = np.concatenate([-meta["product_coefficient"], np.zeros(len(lower) - flow_count)])
    run = _solve(objective, builder, lower, upper, integrality, "问题4可持续周产能最大化")
    gross_product = float(run.x[:flow_count] @ meta["product_coefficient"])
    solution = _decode_solution(data, candidates, run, meta, gross_product, "4", "全供应网络产能最大化 MILP")
    solution["maximum_weekly_production_m3"] = gross_product
    solution["capacity_increase_m3"] = gross_product - DEMAND_BASE
    solution["capacity_increase_ratio"] = gross_product / DEMAND_BASE - 1.0
    solution["objective"] = _objective_values(solution, data)
    run.status["model_type"] = "linear_program_with_soft_single_carrier_indicator"
    return solution, [run.status]
