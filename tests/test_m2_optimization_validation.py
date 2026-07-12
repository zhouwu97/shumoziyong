from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from canonical_json import result_equivalence_sha256  # noqa: E402
from validate_2024c_dryland import validate_decision  # noqa: E402


def _materials(root: Path) -> tuple[Path, Path, Path]:
    attachment_1 = root / "附件1.xlsx"
    book_1 = Workbook()
    land = book_1.active
    land.title = "乡村的现有耕地"
    land.append(["地块名称", "地块类型", "地块面积/亩"])
    land.append(["A1", "平旱地", 10])
    book_1.save(attachment_1)

    attachment_2 = root / "附件2.xlsx"
    book_2 = Workbook()
    stats = book_2.active
    stats.title = "2023年统计的相关数据"
    stats.append(["序号", "作物编号", "作物名称", "地块类型", "种植季次", "亩产量/斤", "种植成本/(元/亩)", "销售单价/(元/斤)"])
    stats.append([1, 1, "黄豆", "平旱地", "单季", 100, 10, "2.00-4.00"])
    book_2.save(attachment_2)
    manifest = root / "material_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    return attachment_1, attachment_2, manifest


def _decision(path: Path, *, crop_id: int = 1, objective: float = 2900) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "problem_id": "2024-C",
                "scope": "q1_dryland_single_season_baseline",
                "task_id": "Q1_DRYLAND_BASELINE",
                "assignments": [{"plot_id": "A1", "crop_id": crop_id, "area_mu": 10}],
                "objective_reported": objective,
            }
        ),
        encoding="utf-8",
    )


def test_validator_recomputes_objective_from_decisions_and_inputs(tmp_path: Path) -> None:
    attachment_1, attachment_2, manifest = _materials(tmp_path)
    decision = tmp_path / "decision_variables.json"
    _decision(decision)

    report = validate_decision(decision, attachment_1, attachment_2, manifest)

    assert report["feasible"] is True
    assert report["objective_recomputed"] == 2900
    assert report["objective_abs_error"] == 0


def test_validator_rejects_invalid_assignment_without_using_reported_metrics(tmp_path: Path) -> None:
    attachment_1, attachment_2, manifest = _materials(tmp_path)
    decision = tmp_path / "decision_variables.json"
    _decision(decision, crop_id=15, objective=999999)

    report = validate_decision(decision, attachment_1, attachment_2, manifest)

    assert report["feasible"] is False
    assert report["invalid_assignment_count"] == 1


def test_result_equivalence_digest_ignores_key_order_and_rounds_float_noise() -> None:
    assert result_equivalence_sha256({"b": 1.0000000001, "a": 2}) == result_equivalence_sha256(
        {"a": 2, "b": 1.0}
    )
