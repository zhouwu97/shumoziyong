"""2024-C A0 官方数据与输出合同测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.problem_2024_c.data_loader import default_audit_output_path, load_problem_data
from domains.problem_2024_c.official_output_schema import (
    Assignment,
    export_official_workbook,
    import_official_workbook,
    inspect_template,
)
from official_integration import official_2024c_attachments


@pytest.fixture(scope="module")
def official_material_root() -> Path:
    attachment_1, _ = official_2024c_attachments()
    return attachment_1.parents[2]


@pytest.mark.official_integration
def test_full_loader_freezes_all_official_rows(official_material_root: Path) -> None:
    data = load_problem_data(official_material_root)
    assert len(data.plots) == 54
    assert len(data.crops) == 41
    assert len(data.planting_2023) == 87
    assert len(data.statistics) == 107
    assert len(data.expected_sales_2023) == 47
    assert sum(item.area_mu for item in data.plots.values()) == pytest.approx(1213.0)
    assert data.planting_2023[-1].plot_id == "F4"


@pytest.mark.official_integration
def test_official_template_round_trip_preserves_decisions(
    official_material_root: Path, tmp_path: Path
) -> None:
    unicode_root = tmp_path / "中文工作区"
    expected_output = unicode_root.resolve() / "capability_evidence" / "2024_c_full_closure" / "a0_official_materials_audit.json"
    assert default_audit_output_path(unicode_root) == expected_output

    data = load_problem_data(official_material_root)
    template = official_material_root / "2024_C" / "templates" / "result1_1.xlsx"
    before = inspect_template(template)
    assignments = [
        Assignment("A1", 2024, "单季", 1, 12.5),
        Assignment("F1", 2024, "第一季", 17, 0.3),
        Assignment("F1", 2024, "第二季", 18, 0.3),
    ]
    output = tmp_path / "result1_1.xlsx"
    export_official_workbook(template, output, data, assignments)
    after = inspect_template(output)
    restored = import_official_workbook(output, data)
    assert before == after
    assert restored == assignments
