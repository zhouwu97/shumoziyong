"""按 assumptions.md 的已公开规则生成并汇总 Q2/Q3 情景。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from load_data import ProblemData, YEARS


Q2_SEED = 2024071402
Q3_SEED = 2024071403
Q3_COMPARISON_SEED = 2024071499


def all_groups(data: ProblemData) -> list[tuple[int, str, str]]:
    """只保留题面允许、可取得参数的销售统计组。"""
    groups: set[tuple[int, str, str]] = set()
    for _, plot in data.plots.iterrows():
        plot_type = str(plot["地块类型"])
        for slot in data.slots(plot_type):
            for crop_id in data.eligible_crops(plot_type, slot):
                groups.add((crop_id, plot_type, slot))
    return sorted(groups)


def _crop_family(crop_id: int) -> str:
    if crop_id <= 16:
        return "粮食"
    if crop_id <= 37:
        return "蔬菜"
    return "食用菌"


def _scenario_rows(data: ProblemData, seed: int, count: int, correlated: bool) -> pd.DataFrame:
    rng = np.random.Generator(np.random.PCG64(seed))
    groups = all_groups(data)
    crop_ids = sorted({group[0] for group in groups})
    rows: list[dict[str, object]] = []
    complementary = {21: 29, 29: 21, 22: 24, 24: 22, 23: 30, 30: 23}
    for scenario_id in range(count):
        for year_index, year in enumerate(YEARS, start=1):
            demand_rate = {crop: (rng.uniform(0.05, 0.10) if crop in {6, 7} else rng.uniform(-0.05, 0.05)) for crop in crop_ids}
            yield_shock = {crop: rng.uniform(-0.10, 0.10) for crop in crop_ids}
            price_shock = {crop: rng.normal(0.0, 0.025) for crop in crop_ids}
            if correlated:
                cost_shock = {
                    crop: 0.40 * price_shock[crop] + np.sqrt(0.84) * rng.normal(0.0, 0.025)
                    for crop in crop_ids
                }
                vegetable_prices = [price_shock[crop] for crop in crop_ids if 17 <= crop <= 37]
                vegetable_mean = float(np.mean(vegetable_prices))
                demand_shock = {}
                for crop in crop_ids:
                    substitute = 0.12 * (vegetable_mean - price_shock[crop]) if 17 <= crop <= 37 else 0.0
                    partner = complementary.get(crop)
                    complement = 0.08 * demand_rate.get(partner, 0.0) if partner else 0.0
                    demand_shock[crop] = -0.30 * price_shock[crop] + substitute + complement
            else:
                cost_shock = {crop: 0.0 for crop in crop_ids}
                demand_shock = {crop: 0.0 for crop in crop_ids}
            for crop_id, plot_type, slot in groups:
                base_yield, base_cost, base_price = data.parameters((crop_id, plot_type, slot))
                base_demand = data.demand_2023.get((crop_id, plot_type, slot), 0.0)
                family = _crop_family(crop_id)
                demand_multiplier = (1.0 + demand_rate[crop_id] + demand_shock[crop_id]) ** year_index
                yield_multiplier = max(0.01, 1.0 + yield_shock[crop_id])
                if family == "粮食":
                    price_multiplier = 1.0
                elif family == "蔬菜":
                    growth = np.clip(0.05 + price_shock[crop_id], 0.03, 0.07)
                    price_multiplier = (1.0 + growth) ** year_index
                else:
                    decline = 0.05 if crop_id == 41 else np.clip(0.03 - price_shock[crop_id], 0.01, 0.05)
                    price_multiplier = (1.0 - decline) ** year_index
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "year": year,
                        "crop_id": crop_id,
                        "plot_type": plot_type,
                        "season": slot,
                        "demand": base_demand * max(0.01, demand_multiplier),
                        "yield_per_mu": base_yield * yield_multiplier,
                        "cost_per_mu": base_cost * (1.05**year_index) * max(0.01, 1.0 + cost_shock[crop_id]),
                        "price": base_price * price_multiplier,
                    }
                )
    return pd.DataFrame(rows)


def generate_q2(data: ProblemData, count: int = 128) -> pd.DataFrame:
    return _scenario_rows(data, Q2_SEED, count, correlated=False)


def generate_q3(data: ProblemData, count: int = 128, comparison: bool = False) -> pd.DataFrame:
    return _scenario_rows(data, Q3_COMPARISON_SEED if comparison else Q3_SEED, count, correlated=True)


def deterministic_parameters(data: ProblemData) -> pd.DataFrame:
    rows = []
    for year in YEARS:
        for crop_id, plot_type, slot in all_groups(data):
            yield_per_mu, cost_per_mu, price = data.parameters((crop_id, plot_type, slot))
            rows.append(
                {
                    "year": year,
                    "crop_id": crop_id,
                    "plot_type": plot_type,
                    "season": slot,
                    "demand": data.demand_2023.get((crop_id, plot_type, slot), 0.0),
                    "yield_per_mu": yield_per_mu,
                    "cost_per_mu": cost_per_mu,
                    "price": price,
                }
            )
    return pd.DataFrame(rows)


def robust_parameters(samples: pd.DataFrame) -> pd.DataFrame:
    """将保存的样本压缩为求解用 10% 保守分位参数表。"""
    group_columns = ["year", "crop_id", "plot_type", "season"]
    grouped = samples.groupby(group_columns, as_index=False)
    conservative = grouped.agg(
        demand=("demand", lambda series: float(series.quantile(0.10))),
        yield_per_mu=("yield_per_mu", lambda series: float(series.quantile(0.10))),
        cost_per_mu=("cost_per_mu", lambda series: float(series.quantile(0.90))),
        price=("price", lambda series: float(series.quantile(0.10))),
    )
    return conservative


def save_scenarios(samples: pd.DataFrame, output_dir: Path, seed: int, mode: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    # 17 位有效数字保证 IEEE-754 双精度经 CSV 往返后仍可在 1e-12 标准内逐项复现。
    samples.to_csv(output_dir / "scenario_samples.csv", index=False, float_format="%.17g")
    (output_dir / "random_seed.json").write_text(
        '{\n  "mode": "' + mode + '",\n  "generator": "PCG64",\n  "seed": ' + str(seed) + "\n}\n",
        encoding="utf-8",
    )
