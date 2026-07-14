"""构造 2024-C 的混合整数线性模型；不负责结果复算。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from load_data import LEGUMES, YEARS, ProblemData


@dataclass
class BuiltModel:
    """求解所需对象及变量索引，供导出模块精确恢复决策变量。"""

    objective: np.ndarray
    integrality: np.ndarray
    bounds: Bounds
    constraints: LinearConstraint
    x_index: dict[tuple[str, int, str, int], int]
    z_index: dict[tuple[str, int, str, int], int]
    mode_index: dict[tuple[str, int], int]
    q_index: dict[tuple[int, int, str], int]
    parameter_lookup: dict[tuple[int, int, str, str], dict[str, float]]


class _Rows:
    """以稀疏三元组累积线性约束，避免构造稠密大矩阵。"""

    def __init__(self) -> None:
        self.row_ids: list[int] = []
        self.col_ids: list[int] = []
        self.values: list[float] = []
        self.lower: list[float] = []
        self.upper: list[float] = []

    def add(self, coefficients: dict[int, float], lower: float = -np.inf, upper: float = np.inf) -> None:
        row = len(self.lower)
        for column, value in coefficients.items():
            if value:
                self.row_ids.append(row)
                self.col_ids.append(column)
                self.values.append(value)
        self.lower.append(lower)
        self.upper.append(upper)

    def constraint(self, variable_count: int) -> LinearConstraint:
        matrix = coo_matrix(
            (self.values, (self.row_ids, self.col_ids)), shape=(len(self.lower), variable_count)
        ).tocsr()
        return LinearConstraint(matrix, np.asarray(self.lower), np.asarray(self.upper))


def _parameter_lookup(parameters: pd.DataFrame) -> dict[tuple[int, int, str, str], dict[str, float]]:
    result: dict[tuple[int, int, str, str], dict[str, float]] = {}
    for row in parameters.to_dict("records"):
        key = (int(row["year"]), int(row["crop_id"]), str(row["plot_type"]), str(row["season"]))
        result[key] = {name: float(row[name]) for name in ("demand", "yield_per_mu", "cost_per_mu", "price")}
    return result


def _adjacent_pairs(data: ProblemData) -> list[tuple[tuple[str, int, str], tuple[str, int, str]]]:
    """仅为同作物可能连续的实际有效季建立相邻对。"""
    pairs: list[tuple[tuple[str, int, str], tuple[str, int, str]]] = []
    for _, plot in data.plots.iterrows():
        plot_id, plot_type = str(plot["地块名称"]), str(plot["地块类型"])
        # 除智慧大棚外，合同规定每一个可用季次都按相邻年份检查。
        for slot in data.slots(plot_type):
            for year in YEARS[:-1]:
                pairs.append(((plot_id, year, slot), (plot_id, year + 1, slot)))
        if plot_type == "智慧大棚":
            for year in YEARS:
                pairs.append(((plot_id, year, "第一季"), (plot_id, year, "第二季")))
                if year < YEARS[-1]:
                    pairs.append(((plot_id, year, "第二季"), (plot_id, year + 1, "第一季")))
    return pairs


def build_model(data: ProblemData, parameters: pd.DataFrame, alpha: float) -> BuiltModel:
    """按固定参数表构造可行域与线性收入目标；返回但不求解。"""
    params = _parameter_lookup(parameters)
    objective: list[float] = []
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []
    integrality: list[int] = []
    x_index: dict[tuple[str, int, str, int], int] = {}
    z_index: dict[tuple[str, int, str, int], int] = {}
    mode_index: dict[tuple[str, int], int] = {}
    q_index: dict[tuple[int, int, str], int] = {}

    def add_variable(cost: float, lower: float, upper: float, integer: bool) -> int:
        index = len(objective)
        objective.append(cost)
        lower_bounds.append(lower)
        upper_bounds.append(upper)
        integrality.append(1 if integer else 0)
        return index

    # 面积变量与活动二元变量一一对应，活动变量为重茬检查提供线性表达。
    for _, plot in data.plots.iterrows():
        plot_id = str(plot["地块名称"])
        plot_type = str(plot["地块类型"])
        area = float(plot["地块面积/亩"])
        for year in YEARS:
            if plot_type == "水浇地":
                mode_index[(plot_id, year)] = add_variable(0.0, 0.0, 1.0, True)
            for slot in data.slots(plot_type):
                for crop_id in data.eligible_crops(plot_type, slot):
                    p_key = (year, crop_id, plot_type, slot)
                    if p_key not in params:
                        raise KeyError(f"参数表缺少 {p_key}")
                    parameter = params[p_key]
                    key = (plot_id, year, slot, crop_id)
                    x_index[key] = add_variable(
                        parameter["cost_per_mu"] - alpha * parameter["price"] * parameter["yield_per_mu"],
                        0.0,
                        area,
                        False,
                    )
                    z_index[key] = add_variable(0.01, 0.0, 1.0, True)

    # 正常销售量按公开合同的作物—季次维度建立，跨地块类型合并。
    groups = sorted({(crop_id, slot) for _, _, slot, crop_id in x_index})
    for year in YEARS:
        for crop_id, slot in groups:
            matching = [value for key, value in params.items() if key[0] == year and key[1] == crop_id and key[3] == slot]
            if not matching:
                raise KeyError(f"参数表缺少销售组 {(year, crop_id, slot)}")
            parameter = matching[0]
            if any(abs(value["demand"] - parameter["demand"]) > 1e-9 or abs(value["price"] - parameter["price"]) > 1e-9 for value in matching[1:]):
                raise ValueError(f"销售组 {(year, crop_id, slot)} 的需求或单价不一致")
            q_index[(year, crop_id, slot)] = add_variable(
                -(1.0 - alpha) * parameter["price"], 0.0, parameter["demand"], False
            )

    rows = _Rows()
    # C01：每个实际可种季的容量。
    for _, plot in data.plots.iterrows():
        plot_id = str(plot["地块名称"])
        plot_type = str(plot["地块类型"])
        area = float(plot["地块面积/亩"])
        for year in YEARS:
            for slot in data.slots(plot_type):
                variables = {
                    x_index[(plot_id, year, slot, crop_id)]: 1.0
                    for crop_id in data.eligible_crops(plot_type, slot)
                }
                rows.add(variables, upper=area)
                for crop_id in data.eligible_crops(plot_type, slot):
                    key = (plot_id, year, slot, crop_id)
                    # x <= A z：正面积才视为作物活动。
                    rows.add({x_index[key]: 1.0, z_index[key]: -area}, upper=0.0)
                    if plot_type == "水浇地":
                        mode = mode_index[(plot_id, year)]
                        if slot == "单季":
                            rows.add({x_index[key]: 1.0, mode: -area}, upper=0.0)
                        else:
                            rows.add({x_index[key]: 1.0, mode: area}, upper=area)

    # C03：规划期内相邻有效季不得出现同作物。
    for left, right in _adjacent_pairs(data):
        left_plot, left_year, left_slot = left
        right_plot, right_year, right_slot = right
        left_crops = set(data.eligible_crops(data.plots.loc[left_plot, "地块类型"], left_slot))
        right_crops = set(data.eligible_crops(data.plots.loc[right_plot, "地块类型"], right_slot))
        for crop_id in left_crops & right_crops:
            rows.add(
                {
                    z_index[(left_plot, left_year, left_slot, crop_id)]: 1.0,
                    z_index[(right_plot, right_year, right_slot, crop_id)]: 1.0,
                },
                upper=1.0,
            )

    # 2023→2024 历史边界：同季跨年；智慧大棚再补连续季次边界。
    for _, plot in data.plots.iterrows():
        plot_id = str(plot["地块名称"])
        plot_type = str(plot["地块类型"])
        for slot in data.slots(plot_type):
            for crop_id in data.history_crops_for_season(plot_id, slot) & set(data.eligible_crops(plot_type, slot)):
                rows.add({z_index[(plot_id, 2024, slot, crop_id)]: 1.0}, upper=0.0)
        if plot_type == "智慧大棚":
            for crop_id in data.history_crops_for_season(plot_id, "第二季") & set(data.eligible_crops(plot_type, "第一季")):
                rows.add({z_index[(plot_id, 2024, "第一季", crop_id)]: 1.0}, upper=0.0)

    # C04：含 2023 历史的六个完整滚动三年豆类窗口。
    for _, plot in data.plots.iterrows():
        plot_id = str(plot["地块名称"])
        plot_type = str(plot["地块类型"])
        area = float(plot["地块面积/亩"])
        history_beans = float(
            data.history.loc[
                (data.history["种植地块"] == plot_id) & data.history["作物编号"].isin(LEGUMES), "种植面积/亩"
            ].sum()
        )
        for start in range(2023, 2029):
            coefficients: dict[int, float] = {}
            if start == 2023:
                # 历史豆类面积移至右端常数，保持矩阵只含决策变量。
                required = area - history_beans
            else:
                required = area
            for year in range(max(2024, start), start + 3):
                for slot in data.slots(plot_type):
                    for crop_id in set(data.eligible_crops(plot_type, slot)) & LEGUMES:
                        coefficients[x_index[(plot_id, year, slot, crop_id)]] = 1.0
            rows.add(coefficients, lower=required)

    # C05：正常销售量不得超过产量，也不得超过相应统计组的销售基线/情景值。
    for (year, crop_id, slot), q_variable in q_index.items():
        coefficients = {q_variable: 1.0}
        for _, plot in data.plots.iterrows():
            plot_type = str(plot["地块类型"])
            if plot["地块类型"] == plot_type and crop_id in data.eligible_crops(plot_type, slot):
                x_variable = x_index[(str(plot["地块名称"]), year, slot, crop_id)]
                coefficients[x_variable] = -params[(year, crop_id, plot_type, slot)]["yield_per_mu"]
        rows.add(coefficients, upper=0.0)

    count = len(objective)
    return BuiltModel(
        objective=np.asarray(objective),
        integrality=np.asarray(integrality),
        bounds=Bounds(np.asarray(lower_bounds), np.asarray(upper_bounds)),
        constraints=rows.constraint(count),
        x_index=x_index,
        z_index=z_index,
        mode_index=mode_index,
        q_index=q_index,
        parameter_lookup=params,
    )


def solve_model(model: BuiltModel, time_limit: float = 90.0):
    """调用 HiGHS；调用方必须用独立复算器决定正式目标。"""
    return milp(
        c=model.objective,
        integrality=model.integrality,
        bounds=model.bounds,
        constraints=model.constraints,
        options={"time_limit": time_limit, "mip_rel_gap": 1e-7, "disp": False},
    )
