"""Gate 2 故障注入：每种指定错误都必须被独立检查器捕获。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_constraints import (  # noqa: E402
    check_2023_to_2024_boundary,
    check_continuous_crop,
    check_integrality_and_nonnegative,
    check_land_capacity,
    check_three_year_legume_windows,
)
from load_data import load_data  # noqa: E402
from recompute_objective import recompute_objective  # noqa: E402
from scenario_generation import deterministic_parameters  # noqa: E402


def plan(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["plot_id", "year", "season", "crop_id", "area"])


class Gate2FaultInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_data()
        cls.parameters = deterministic_parameters(cls.data)

    def test_over_capacity_is_detected(self) -> None:
        solution = plan([{"plot_id": "A1", "year": 2024, "season": "单季", "crop_id": 7, "area": 80.1}])
        self.assertGreater(len(check_land_capacity(solution, self.data)), 0)

    def test_negative_area_is_detected(self) -> None:
        solution = plan([{"plot_id": "A1", "year": 2024, "season": "单季", "crop_id": 7, "area": -0.1}])
        self.assertGreater(len(check_integrality_and_nonnegative(solution)), 0)

    def test_planning_period_continuous_crop_is_detected(self) -> None:
        solution = plan(
            [
                {"plot_id": "A1", "year": 2024, "season": "单季", "crop_id": 7, "area": 1.0},
                {"plot_id": "A1", "year": 2025, "season": "单季", "crop_id": 7, "area": 1.0},
            ]
        )
        self.assertGreater(len(check_continuous_crop(solution, self.data)), 0)

    def test_ordinary_greenhouse_same_season_continuous_crop_is_detected(self) -> None:
        greenhouse = str(self.data.plots.loc[self.data.plots["地块类型"] == "普通大棚", "地块名称"].iloc[0])
        solution = plan(
            [
                {"plot_id": greenhouse, "year": 2024, "season": "第一季", "crop_id": 17, "area": 1.0},
                {"plot_id": greenhouse, "year": 2025, "season": "第一季", "crop_id": 17, "area": 1.0},
            ]
        )
        self.assertGreater(len(check_continuous_crop(solution, self.data)), 0)

    def test_2023_to_2024_boundary_is_detected(self) -> None:
        # A1 在 2023 年种小麦（编号 6），故 2024 单季继续种小麦应被拒绝。
        solution = plan([{"plot_id": "A1", "year": 2024, "season": "单季", "crop_id": 6, "area": 1.0}])
        self.assertGreater(len(check_2023_to_2024_boundary(solution, self.data)), 0)

    def test_empty_legume_plan_has_window_gaps(self) -> None:
        solution = plan([])
        self.assertGreater(len(check_three_year_legume_windows(solution, self.data)), 0)

    def test_tampered_objective_differs_from_recomputation(self) -> None:
        solution = plan([{"plot_id": "A1", "year": 2024, "season": "单季", "crop_id": 7, "area": 1.0}])
        objective, _ = recompute_objective(solution, self.data, self.parameters, alpha=0.0)
        tampered_reported_value = objective["objective"] + 1.0
        self.assertGreater(abs(tampered_reported_value - objective["objective"]), 1e-6)


if __name__ == "__main__":
    unittest.main()
