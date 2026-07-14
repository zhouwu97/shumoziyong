"""从导出的原始面积变量独立复算收入与目标值。"""

from __future__ import annotations

import pandas as pd

from load_data import ProblemData


def _parameter_dict(parameters: pd.DataFrame) -> dict[tuple[int, int, str, str], dict[str, float]]:
    return {
        (int(row.year), int(row.crop_id), str(row.plot_type), str(row.season)): {
            "demand": float(row.demand),
            "yield_per_mu": float(row.yield_per_mu),
            "cost_per_mu": float(row.cost_per_mu),
            "price": float(row.price),
        }
        for row in parameters.itertuples(index=False)
    }


def recompute_objective(
    solution: pd.DataFrame, data: ProblemData, parameters: pd.DataFrame, alpha: float
) -> tuple[dict[str, float], pd.DataFrame]:
    """只依赖原始面积和参数表复算；不读取求解器目标或辅助变量。"""
    if solution.empty:
        solution = pd.DataFrame(columns=["plot_id", "year", "season", "crop_id", "area"])
    # 零面积变量是完整原始决策记录的一部分，但不影响任何产量或金额；
    # 情景批量复算时跳过它们，避免重复处理数万条严格为零的记录。
    working = solution.loc[solution["area"] > 1e-12].copy()
    working["plot_type"] = working["plot_id"].map(data.plots["地块类型"])
    lookup = _parameter_dict(parameters)

    def parameter(row: pd.Series, name: str) -> float:
        key = (int(row["year"]), int(row["crop_id"]), str(row["plot_type"]), str(row["season"]))
        return lookup[key][name]

    for field in ("demand", "yield_per_mu", "cost_per_mu", "price"):
        working[field] = working.apply(lambda row: parameter(row, field), axis=1)
    working["production"] = working["area"] * working["yield_per_mu"]
    working["planting_cost"] = working["area"] * working["cost_per_mu"]
    group_columns = ["year", "crop_id", "plot_type", "season"]
    grouped = (
        working.groupby(group_columns, as_index=False)
        .agg(production=("production", "sum"), planting_cost=("planting_cost", "sum"), demand=("demand", "first"), price=("price", "first"))
    )
    grouped["normal_sales"] = grouped[["production", "demand"]].min(axis=1)
    grouped["excess_sales"] = (grouped["production"] - grouped["normal_sales"]).clip(lower=0.0)
    grouped["normal_revenue"] = grouped["normal_sales"] * grouped["price"]
    grouped["excess_revenue"] = alpha * grouped["excess_sales"] * grouped["price"]
    grouped["profit"] = grouped["normal_revenue"] + grouped["excess_revenue"] - grouped["planting_cost"]
    total_cost = float(grouped["planting_cost"].sum())
    normal_revenue = float(grouped["normal_revenue"].sum())
    excess_revenue = float(grouped["excess_revenue"].sum())
    summary = {
        "objective": normal_revenue + excess_revenue - total_cost,
        "normal_revenue": normal_revenue,
        "excess_revenue": excess_revenue,
        "planting_cost": total_cost,
        "total_production": float(grouped["production"].sum()),
        "normal_sales": float(grouped["normal_sales"].sum()),
        "excess_sales": float(grouped["excess_sales"].sum()),
    }
    return summary, grouped


def evaluate_samples(
    solution: pd.DataFrame, data: ProblemData, samples: pd.DataFrame, alpha: float
) -> pd.DataFrame:
    """对保存的每个随机情景逐一复算，供 Q2/Q3 风险摘要和独立比较使用。"""
    records = []
    for scenario_id, parameter_table in samples.groupby("scenario_id"):
        summary, _ = recompute_objective(solution, data, parameter_table.drop(columns="scenario_id"), alpha)
        records.append({"scenario_id": int(scenario_id), **summary})
    return pd.DataFrame(records)
