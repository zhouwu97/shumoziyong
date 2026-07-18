"""2024-C Q1 确定性种植规划 MILP 求解器。"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .data_model import DRYLAND_TYPES, LEGUME_CROP_IDS, YEARS, ProblemData
from .official_output_schema import Assignment


@dataclass(frozen=True)
class MarketParameter:
    demand_jin: float
    yield_jin_per_mu: float
    cost_yuan_per_mu: float
    price_yuan_per_jin: float


ParameterKey = tuple[int, int, str, str]


@dataclass(frozen=True)
class SolverSettings:
    minimum_area_ratio: float = 0.10
    minimum_area_mu: float = 0.30
    fragmentation_penalty_yuan: float = 1.0
    time_limit_seconds: float = 180.0
    mip_relative_gap: float = 1e-5
    random_seed: int = 20240718


@dataclass(frozen=True)
class SolverResult:
    scenario_id: str
    assignments: tuple[Assignment, ...]
    objective_yuan: float
    fragmentation_count: int
    solver_status: int
    solver_message: str
    mip_gap: float | None
    optimality_proven: bool
    settings: SolverSettings


@dataclass
class _BuiltModel:
    objective: np.ndarray
    integrality: np.ndarray
    bounds: Bounds
    constraints: LinearConstraint
    area_index: dict[tuple[str, int, str, int], int]
    active_index: dict[tuple[str, int, str, int], int]
    normal_sales_index: dict[tuple[int, int, str], int]


class _ConstraintRows:
    def __init__(self) -> None:
        self.rows: list[int] = []
        self.columns: list[int] = []
        self.values: list[float] = []
        self.lower: list[float] = []
        self.upper: list[float] = []

    def add(
        self,
        coefficients: Mapping[int, float],
        lower: float = -np.inf,
        upper: float = np.inf,
    ) -> None:
        row = len(self.lower)
        for column, value in coefficients.items():
            if value:
                self.rows.append(row)
                self.columns.append(column)
                self.values.append(float(value))
        self.lower.append(float(lower))
        self.upper.append(float(upper))

    def build(self, variable_count: int) -> LinearConstraint:
        matrix = coo_matrix(
            (self.values, (self.rows, self.columns)),
            shape=(len(self.lower), variable_count),
        ).tocsr()
        return LinearConstraint(matrix, np.asarray(self.lower), np.asarray(self.upper))


def deterministic_parameters(data: ProblemData) -> dict[ParameterKey, MarketParameter]:
    """Q1 使用 2023 中点价格和按作物-季次聚合的销量基线。"""
    result: dict[ParameterKey, MarketParameter] = {}
    for year in YEARS:
        for plot_type in sorted({plot.plot_type for plot in data.plots.values()}):
            for season in data.seasons(plot_type):
                for crop_id in data.eligible_crops(plot_type, season):
                    stat = data.stat(crop_id, plot_type, season)
                    result[(year, crop_id, plot_type, season)] = MarketParameter(
                        demand_jin=data.expected_sales_2023.get((crop_id, season), 0.0),
                        yield_jin_per_mu=stat.yield_jin_per_mu,
                        cost_yuan_per_mu=stat.cost_yuan_per_mu,
                        price_yuan_per_jin=stat.price_mid_yuan_per_jin,
                    )
    return result


def _adjacent_repeat_pairs(data: ProblemData) -> list[tuple[tuple[str, int, str], tuple[str, int, str]]]:
    """只枚举实际相邻且作物集合可能重叠的季次。"""
    pairs: list[tuple[tuple[str, int, str], tuple[str, int, str]]] = []
    for plot in data.plots.values():
        if plot.plot_type in DRYLAND_TYPES:
            pairs.extend(
                ((plot.plot_id, year, "单季"), (plot.plot_id, year + 1, "单季"))
                for year in YEARS[:-1]
            )
        elif plot.plot_type == "水浇地":
            pairs.extend(
                ((plot.plot_id, year, "单季"), (plot.plot_id, year + 1, "单季"))
                for year in YEARS[:-1]
            )
        elif plot.plot_type == "智慧大棚":
            for year in YEARS:
                pairs.append(
                    ((plot.plot_id, year, "第一季"), (plot.plot_id, year, "第二季"))
                )
                if year < YEARS[-1]:
                    pairs.append(
                        (
                            (plot.plot_id, year, "第二季"),
                            (plot.plot_id, year + 1, "第一季"),
                        )
                    )
    return pairs


def _build_model(
    data: ProblemData,
    parameters: Mapping[ParameterKey, MarketParameter],
    surplus_price_fraction: float,
    settings: SolverSettings,
) -> _BuiltModel:
    objective: list[float] = []
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []
    integrality: list[int] = []
    area_index: dict[tuple[str, int, str, int], int] = {}
    active_index: dict[tuple[str, int, str, int], int] = {}
    water_mode_index: dict[tuple[str, int], int] = {}
    normal_sales_index: dict[tuple[int, int, str], int] = {}

    def add(cost: float, lower: float, upper: float, integer: bool = False) -> int:
        index = len(objective)
        objective.append(float(cost))
        lower_bounds.append(float(lower))
        upper_bounds.append(float(upper))
        integrality.append(1 if integer else 0)
        return index

    for plot in data.plots.values():
        for year in YEARS:
            if plot.plot_type == "水浇地":
                water_mode_index[(plot.plot_id, year)] = add(0.0, 0.0, 1.0, True)
            for season in data.seasons(plot.plot_type):
                for crop_id in data.eligible_crops(plot.plot_type, season):
                    parameter = parameters[(year, crop_id, plot.plot_type, season)]
                    key = (plot.plot_id, year, season, crop_id)
                    unit_surplus_revenue = (
                        surplus_price_fraction
                        * parameter.price_yuan_per_jin
                        * parameter.yield_jin_per_mu
                    )
                    area_index[key] = add(
                        parameter.cost_yuan_per_mu - unit_surplus_revenue,
                        0.0,
                        plot.area_mu,
                    )
                    active_index[key] = add(
                        settings.fragmentation_penalty_yuan, 0.0, 1.0, True
                    )

    sales_groups = sorted({(year, crop_id, season) for _, year, season, crop_id in area_index})
    for year, crop_id, season in sales_groups:
        matching = [
            value
            for key, value in parameters.items()
            if key[0] == year and key[1] == crop_id and key[3] == season
        ]
        reference = matching[0]
        if any(
            abs(value.demand_jin - reference.demand_jin) > 1e-9
            or abs(value.price_yuan_per_jin - reference.price_yuan_per_jin) > 1e-9
            for value in matching[1:]
        ):
            raise ValueError(f"同一销售组的销量或价格不一致：{year}-{crop_id}-{season}")
        normal_sales_index[(year, crop_id, season)] = add(
            -(1.0 - surplus_price_fraction) * reference.price_yuan_per_jin,
            0.0,
            reference.demand_jin,
        )

    rows = _ConstraintRows()
    for plot in data.plots.values():
        minimum_area = min(
            plot.area_mu,
            max(settings.minimum_area_mu, settings.minimum_area_ratio * plot.area_mu),
        )
        for year in YEARS:
            for season in data.seasons(plot.plot_type):
                keys = [
                    (plot.plot_id, year, season, crop_id)
                    for crop_id in data.eligible_crops(plot.plot_type, season)
                ]
                rows.add({area_index[key]: 1.0 for key in keys}, upper=plot.area_mu)
                for key in keys:
                    rows.add(
                        {area_index[key]: 1.0, active_index[key]: -plot.area_mu}, upper=0.0
                    )
                    rows.add(
                        {area_index[key]: 1.0, active_index[key]: -minimum_area}, lower=0.0
                    )
                    if plot.plot_type == "水浇地":
                        mode = water_mode_index[(plot.plot_id, year)]
                        if season == "单季":
                            rows.add({area_index[key]: 1.0, mode: -plot.area_mu}, upper=0.0)
                        else:
                            rows.add({area_index[key]: 1.0, mode: plot.area_mu}, upper=plot.area_mu)

    for left, right in _adjacent_repeat_pairs(data):
        plot_id, left_year, left_season = left
        _, right_year, right_season = right
        plot_type = data.plots[plot_id].plot_type
        common = set(data.eligible_crops(plot_type, left_season)) & set(
            data.eligible_crops(plot_type, right_season)
        )
        for crop_id in common:
            rows.add(
                {
                    active_index[(plot_id, left_year, left_season, crop_id)]: 1.0,
                    active_index[(plot_id, right_year, right_season, crop_id)]: 1.0,
                },
                upper=1.0,
            )

    # 2023 到 2024 的真实相邻边界。
    for plot in data.plots.values():
        if plot.plot_type in DRYLAND_TYPES:
            boundary_seasons = (("单季", "单季"),)
        elif plot.plot_type == "水浇地":
            boundary_seasons = (("单季", "单季"),)
        elif plot.plot_type == "智慧大棚":
            boundary_seasons = (("第二季", "第一季"),)
        else:
            boundary_seasons = ()
        for historical_season, planned_season in boundary_seasons:
            eligible = set(data.eligible_crops(plot.plot_type, planned_season))
            for record in data.history_for(plot.plot_id, historical_season):
                if record.crop_id in eligible:
                    rows.add(
                        {active_index[(plot.plot_id, 2024, planned_season, record.crop_id)]: 1.0},
                        upper=0.0,
                    )

    # 每个滚动三年窗口的豆类累计面积覆盖整个地块，2023 历史面积进入首窗。
    for plot in data.plots.values():
        history_legume_area = sum(
            item.area_mu
            for item in data.history_for(plot.plot_id)
            if item.crop_id in LEGUME_CROP_IDS
        )
        for start in range(2023, 2029):
            coefficients: dict[int, float] = {}
            for year in range(max(2024, start), start + 3):
                for season in data.seasons(plot.plot_type):
                    for crop_id in set(data.eligible_crops(plot.plot_type, season)) & LEGUME_CROP_IDS:
                        coefficients[area_index[(plot.plot_id, year, season, crop_id)]] = 1.0
            required = plot.area_mu - history_legume_area if start == 2023 else plot.area_mu
            rows.add(coefficients, lower=max(0.0, required))

    for (year, crop_id, season), sales_index in normal_sales_index.items():
        coefficients = {sales_index: 1.0}
        for plot in data.plots.values():
            key = (plot.plot_id, year, season, crop_id)
            if key in area_index:
                parameter = parameters[(year, crop_id, plot.plot_type, season)]
                coefficients[area_index[key]] = -parameter.yield_jin_per_mu
        rows.add(coefficients, upper=0.0)

    count = len(objective)
    return _BuiltModel(
        objective=np.asarray(objective),
        integrality=np.asarray(integrality),
        bounds=Bounds(np.asarray(lower_bounds), np.asarray(upper_bounds)),
        constraints=rows.build(count),
        area_index=area_index,
        active_index=active_index,
        normal_sales_index=normal_sales_index,
    )


def calculate_profit(
    assignments: tuple[Assignment, ...],
    data: ProblemData,
    parameters: Mapping[ParameterKey, MarketParameter],
    surplus_price_fraction: float,
) -> float:
    """仅用于 Solver 结果展示；正式验证使用独立 Validator 实现。"""
    production: dict[tuple[int, int, str], float] = {}
    cost = 0.0
    for item in assignments:
        plot_type = data.plots[item.plot_id].plot_type
        parameter = parameters[(item.year, item.crop_id, plot_type, item.season)]
        key = (item.year, item.crop_id, item.season)
        production[key] = production.get(key, 0.0) + item.area_mu * parameter.yield_jin_per_mu
        cost += item.area_mu * parameter.cost_yuan_per_mu
    revenue = 0.0
    for (year, crop_id, season), amount in production.items():
        matching = next(
            value
            for key, value in parameters.items()
            if key[0] == year and key[1] == crop_id and key[3] == season
        )
        normal = min(amount, matching.demand_jin)
        surplus = max(0.0, amount - matching.demand_jin)
        revenue += matching.price_yuan_per_jin * (
            normal + surplus_price_fraction * surplus
        )
    return revenue - cost


def _assert_feasible_incumbent(model: _BuiltModel, values: np.ndarray) -> None:
    """在返回时限 incumbent 前检查边界、整数性和全部线性约束。"""

    tolerance = 1e-5
    if not np.all(np.isfinite(values)):
        raise RuntimeError("MILP incumbent 包含非有限数值")
    bound_violation = max(
        float(np.max(model.bounds.lb - values, initial=0.0)),
        float(np.max(values - model.bounds.ub, initial=0.0)),
    )
    integer_values = values[model.integrality == 1]
    integrality_violation = float(
        np.max(np.abs(integer_values - np.rint(integer_values)), initial=0.0)
    )
    activity = model.constraints.A @ values
    constraint_violation = max(
        float(np.max(model.constraints.lb - activity, initial=0.0)),
        float(np.max(activity - model.constraints.ub, initial=0.0)),
    )
    if max(bound_violation, integrality_violation, constraint_violation) > tolerance:
        raise RuntimeError(
            "MILP incumbent 不可行："
            f"bound={bound_violation:.3e}, integer={integrality_violation:.3e}, "
            f"constraint={constraint_violation:.3e}"
        )


def solve(
    scenario_id: str,
    data: ProblemData,
    parameters: Mapping[ParameterKey, MarketParameter],
    surplus_price_fraction: float,
    settings: SolverSettings | None = None,
) -> SolverResult:
    settings = settings or SolverSettings()
    model = _build_model(data, parameters, surplus_price_fraction, settings)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Unrecognized options detected:.*random_seed.*",
            category=RuntimeWarning,
        )
        raw = milp(
            c=model.objective,
            integrality=model.integrality,
            bounds=model.bounds,
            constraints=model.constraints,
            options={
                "time_limit": settings.time_limit_seconds,
                "mip_rel_gap": settings.mip_relative_gap,
                "random_seed": settings.random_seed,
                "presolve": True,
                "disp": False,
            },
        )
    if raw.x is None:
        raise RuntimeError(f"{scenario_id} 求解失败：status={raw.status}, {raw.message}")
    _assert_feasible_incumbent(model, raw.x)
    assignments = tuple(
        Assignment(plot_id, year, season, crop_id, float(raw.x[index]))
        for (plot_id, year, season, crop_id), index in model.area_index.items()
        if raw.x[index] > 1e-7
    )
    fragmentation_count = sum(raw.x[index] > 0.5 for index in model.active_index.values())
    return SolverResult(
        scenario_id=scenario_id,
        assignments=assignments,
        objective_yuan=calculate_profit(
            assignments, data, parameters, surplus_price_fraction
        ),
        fragmentation_count=int(fragmentation_count),
        solver_status=int(raw.status),
        solver_message=str(raw.message),
        mip_gap=float(raw.mip_gap) if getattr(raw, "mip_gap", None) is not None else None,
        optimality_proven=bool(raw.success),
        settings=settings,
    )


def solve_q1(
    data: ProblemData, settings: SolverSettings | None = None
) -> tuple[SolverResult, SolverResult]:
    parameters = deterministic_parameters(data)
    return (
        solve("q1_waste", data, parameters, 0.0, settings),
        solve("q1_discount", data, parameters, 0.5, settings),
    )
