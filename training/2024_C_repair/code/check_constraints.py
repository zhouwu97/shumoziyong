"""独立检查 2024-C 的硬约束，不调用求解器状态或模型矩阵。"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from load_data import LEGUMES, YEARS, ProblemData
from recompute_objective import recompute_objective


TOLERANCE = 1e-8


def _positive(solution: pd.DataFrame) -> pd.DataFrame:
    return solution.loc[solution["area"] > TOLERANCE].copy()


def check_land_capacity(solution: pd.DataFrame, data: ProblemData) -> list[dict[str, object]]:
    violations = []
    for keys, amount in solution.groupby(["plot_id", "year", "season"])["area"].sum().items():
        plot_id, year, season = keys
        capacity = float(data.plots.loc[plot_id, "地块面积/亩"])
        if amount > capacity + TOLERANCE:
            violations.append({"plot_id": plot_id, "year": int(year), "season": season, "excess": float(amount - capacity)})
    return violations


def check_crop_land_compatibility(solution: pd.DataFrame, data: ProblemData) -> list[dict[str, object]]:
    violations = []
    for row in _positive(solution).itertuples(index=False):
        if row.plot_id not in data.plots.index:
            violations.append({"plot_id": row.plot_id, "reason": "未知地块"})
            continue
        plot_type = str(data.plots.loc[row.plot_id, "地块类型"])
        if int(row.crop_id) not in data.eligible_crops(plot_type, str(row.season)):
            violations.append({"plot_id": row.plot_id, "year": int(row.year), "season": row.season, "crop_id": int(row.crop_id)})
    return violations


def check_water_mode(solution: pd.DataFrame, data: ProblemData) -> list[dict[str, object]]:
    violations = []
    for plot_id, plot in data.plots.iterrows():
        if plot["地块类型"] != "水浇地":
            continue
        for year in YEARS:
            rows = _positive(solution.loc[(solution["plot_id"] == plot_id) & (solution["year"] == year)])
            rice = float(rows.loc[rows["season"] == "单季", "area"].sum())
            vegetables = float(rows.loc[rows["season"].isin(["第一季", "第二季"]), "area"].sum())
            if rice > TOLERANCE and vegetables > TOLERANCE:
                violations.append({"plot_id": plot_id, "year": year, "rice_area": rice, "vegetable_area": vegetables})
    return violations


def _is_active(solution: pd.DataFrame, plot_id: str, year: int, season: str, crop_id: int) -> bool:
    return bool(
        (
            (solution["plot_id"] == plot_id)
            & (solution["year"] == year)
            & (solution["season"] == season)
            & (solution["crop_id"] == crop_id)
            & (solution["area"] > TOLERANCE)
        ).any()
    )


def check_continuous_crop(solution: pd.DataFrame, data: ProblemData) -> list[dict[str, object]]:
    violations = []
    for plot_id, plot in data.plots.iterrows():
        plot_type = str(plot["地块类型"])
        slot_pairs = [
            (year, season, year + 1, season)
            for season in data.slots(plot_type)
            for year in YEARS[:-1]
        ]
        if plot_type == "智慧大棚":
            for year in YEARS:
                slot_pairs.append((year, "第一季", year, "第二季"))
                if year < YEARS[-1]:
                    slot_pairs.append((year, "第二季", year + 1, "第一季"))
        for year_a, season_a, year_b, season_b in slot_pairs:
            shared = set(data.eligible_crops(plot_type, season_a)) & set(data.eligible_crops(plot_type, season_b))
            for crop_id in shared:
                if _is_active(solution, plot_id, year_a, season_a, crop_id) and _is_active(solution, plot_id, year_b, season_b, crop_id):
                    violations.append({"plot_id": plot_id, "crop_id": crop_id, "from": f"{year_a}-{season_a}", "to": f"{year_b}-{season_b}"})
    return violations


def check_2023_to_2024_boundary(solution: pd.DataFrame, data: ProblemData) -> list[dict[str, object]]:
    violations = []
    for plot_id, plot in data.plots.iterrows():
        plot_type = str(plot["地块类型"])
        for season in data.slots(plot_type):
            for crop_id in data.history_crops_for_season(plot_id, season) & set(data.eligible_crops(plot_type, season)):
                if _is_active(solution, plot_id, 2024, season, crop_id):
                    violations.append({"plot_id": plot_id, "crop_id": crop_id, "season": season})
        if plot_type == "智慧大棚":
            for crop_id in data.history_crops_for_season(plot_id, "第二季") & set(data.eligible_crops(plot_type, "第一季")):
                if _is_active(solution, plot_id, 2024, "第一季", crop_id):
                    violations.append({"plot_id": plot_id, "crop_id": crop_id, "season": "第一季", "rule": "2023第二季到2024第一季"})
    return violations


def check_three_year_legume_windows(solution: pd.DataFrame, data: ProblemData) -> list[dict[str, object]]:
    violations = []
    for plot_id, plot in data.plots.iterrows():
        area = float(plot["地块面积/亩"])
        history_beans = float(
            data.history.loc[
                (data.history["种植地块"] == plot_id) & data.history["作物编号"].isin(LEGUMES), "种植面积/亩"
            ].sum()
        )
        rows = solution.loc[(solution["plot_id"] == plot_id) & solution["crop_id"].isin(LEGUMES)]
        for start in range(2023, 2029):
            amount = float(rows.loc[rows["year"].between(max(2024, start), start + 2), "area"].sum())
            if start == 2023:
                amount += history_beans
            if amount + TOLERANCE < area:
                violations.append({"plot_id": plot_id, "window": f"{start}-{start + 2}", "coverage": amount, "shortfall": area - amount})
    return violations


def check_integrality_and_nonnegative(solution: pd.DataFrame, modes: pd.DataFrame | None = None) -> list[dict[str, object]]:
    violations = []
    for row in solution.loc[solution["area"] < -TOLERANCE].itertuples(index=False):
        violations.append({"kind": "negative_area", "plot_id": row.plot_id, "area": float(row.area)})
    if modes is not None:
        for row in modes.itertuples(index=False):
            if abs(float(row.mode_value) - round(float(row.mode_value))) > TOLERANCE:
                violations.append({"kind": "nonbinary_mode", "plot_id": row.plot_id, "value": float(row.mode_value)})
    return violations


def check_sales_limit(solution: pd.DataFrame, data: ProblemData, parameters: pd.DataFrame, alpha: float) -> list[dict[str, object]]:
    _, groups = recompute_objective(solution, data, parameters, alpha)
    return [
        row._asdict()
        for row in groups.loc[groups["normal_sales"] > groups["demand"] + TOLERANCE].itertuples(index=False)
    ]


def check_constraints(
    solution: pd.DataFrame, data: ProblemData, parameters: pd.DataFrame, alpha: float, modes: pd.DataFrame | None = None
) -> dict[str, object]:
    """返回逐类违约明细和总硬违约数；不把 C07 软偏好算作硬违约。"""
    details = {
        "land_capacity": check_land_capacity(solution, data),
        "crop_land_compatibility": check_crop_land_compatibility(solution, data),
        "water_mode": check_water_mode(solution, data),
        "continuous_crop": check_continuous_crop(solution, data),
        "history_boundary": check_2023_to_2024_boundary(solution, data),
        "three_year_legume": check_three_year_legume_windows(solution, data),
        "integrality_nonnegative": check_integrality_and_nonnegative(solution, modes),
        "sales_limit": check_sales_limit(solution, data, parameters, alpha),
    }
    counts = {name: len(records) for name, records in details.items()}
    return {"violation_counts": counts, "total_hard_violations": sum(counts.values()), "details": details}


def violation_counter(report: dict[str, object]) -> Counter[str]:
    return Counter(report["violation_counts"])
