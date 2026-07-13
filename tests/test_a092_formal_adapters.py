from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validators.problem_boundary.validate import expected_tables, validate_result as validate_boundary  # noqa: E402
from validators.problem_negative.validate import mean_relative_error, validate_result as validate_negative  # noqa: E402
from validators.problem_positive.validate import load_problem_data  # noqa: E402


def test_boundary_adapter_recomputes_frozen_tables() -> None:
    expected = expected_tables()
    report = validate_boundary(expected)

    assert report["valid"] is True
    assert report["max_absolute_difference"] == 0


def test_boundary_adapter_rejects_wrong_width() -> None:
    expected = expected_tables()
    expected["q1"]["coverage_width_m"][0] += 1.0

    assert validate_boundary(expected)["valid"] is False


def test_negative_adapter_recomputes_mre_and_rejects_fake_value() -> None:
    actual = [10.0, 20.0, 30.0]
    predicted = [11.0, 18.0, 33.0]
    mre = mean_relative_error(actual, predicted)
    payload = {
        "curve_checks": [
            {
                "curve_id": "sample",
                "actual_time": actual,
                "predicted_time": predicted,
                "mre_reported": mre,
            }
        ],
        "remaining_time_predictions": [{"case_id": "sample", "remaining_minutes": 12.0}],
    }

    assert validate_negative(payload)["valid"] is True
    payload["curve_checks"][0]["mre_reported"] = 99.0
    assert validate_negative(payload)["valid"] is False


def test_positive_adapter_loads_official_material_contract() -> None:
    attachment_1 = ROOT / "official_materials" / "2024_C" / "attachments" / "附件1.xlsx"
    attachment_2 = ROOT / "official_materials" / "2024_C" / "attachments" / "附件2.xlsx"
    if not attachment_1.is_file() or not attachment_2.is_file():
        pytest.skip("官方大体积附件未在当前 checkout 中下载")
    data = load_problem_data(attachment_1, attachment_2)

    assert len(data["plots"]) == 54
    assert ("平旱地", "单季", 1) in data["stats"]
    assert ("智慧大棚", "第一季", 17) in data["stats"]
    assert math.isclose(data["plots"]["A1"]["area"], 80.0)
