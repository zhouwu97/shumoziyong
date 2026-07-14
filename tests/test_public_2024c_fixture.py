"""公开最小 Excel 回归样本的集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from validators.problem_positive_v2.validate import check_constraints, evaluate_objective, load_problem_data


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "public_2024c_minimal"


@pytest.fixture(scope="module")
def public_data() -> dict:
    return load_problem_data(FIXTURE_ROOT / "附件1.xlsx", FIXTURE_ROOT / "附件2.xlsx")


@pytest.mark.integration_fixture
def test_public_fixture_recovers_merged_cells_and_mixed_values(public_data: dict) -> None:
    assert len(public_data["planting_2023"]) == 3
    assert public_data["planting_2023"][1]["plot_id"] == "A1"
    assert public_data["sales_2023"][(1, "单季")] == 500.0
    assert public_data["stats"][("平旱地", "单季", 1)]["yield"] == 100.0


@pytest.mark.integration_fixture
def test_public_fixture_uses_chinese_sheet_and_smart_greenhouse_fallback(public_data: dict) -> None:
    assert public_data["plots"]["F1"]["type"] == "智慧大棚"
    assert public_data["stats"][("智慧大棚", "第一季", 17)] == public_data["stats"][("普通大棚", "第一季", 17)]


@pytest.mark.integration_fixture
def test_public_fixture_aggregates_sales_by_crop_and_season(public_data: dict) -> None:
    assignments = [
        {"year": 2024, "plot_id": "A1", "season": "单季", "crop_id": 1, "area_mu": 10.0},
    ]
    assert evaluate_objective(assignments, public_data, "q1_waste") == 1395.0


@pytest.mark.integration_fixture
def test_public_fixture_keeps_2023_history_at_smart_greenhouse_boundary(public_data: dict) -> None:
    assignments = [
        {"year": 2024, "plot_id": "F1", "season": "第一季", "crop_id": 17, "area_mu": 0.6},
    ]
    violations, _ = check_constraints(assignments, public_data, 1e-6, check_legume_windows=False)
    assert "continuous_crop:F1:17:2023-第二季->2024-第一季" in violations
