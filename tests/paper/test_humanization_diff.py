from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_humanization_diff import check_humanization_diff  # noqa: E402


def write_pair(tmp_path: Path, before: str, after: str) -> tuple[Path, Path]:
    source = tmp_path / "before.typ"
    output = tmp_path / "after.typ"
    source.write_text(before, encoding="utf-8")
    output.write_text(after, encoding="utf-8")
    return source, output


def test_syntax_only_rewrite_passes(tmp_path: Path) -> None:
    source, output = write_pair(
        tmp_path,
        "结果表明，策略完成 120 件产品，平均等待时间为 10 s。\n",
        "仿真结果中，策略的完成量为 120 件，平均等待时间仍为 10 s。\n",
    )

    report = check_humanization_diff(source, output)

    assert report["status"] == "passed"
    assert report["rewritten_paragraph_count"] == 1


@pytest.mark.parametrize(
    ("before", "after", "field"),
    [
        ("完成 120 件。", "完成 121 件。", "protected_numbers_changed"),
        ("目标为 $ max N $。", "目标为 $ min N $。", "protected_formulas_changed"),
        ("等待时间为 10 s。", "等待时间为 10 min。", "protected_units_changed"),
        ("变量 `T_end` 表示结束时间。", "变量 `T_stop` 表示结束时间。", "protected_symbols_changed"),
        ("该定义见文献 [3]。", "该定义见文献 [4]。", "citations_changed"),
        ("结果见图 2 和表 3。", "结果见图 3 和表 3。", "figure_table_refs_changed"),
        (
            "#three-line-table([结果], (auto,), ([指标], [120]))",
            "#three-line-table([结果], (auto,), ([指标], [121]))",
            "table_cells_changed",
        ),
        ("该策略最大化完成量。", "该策略最小化完成量。", "direction_phrases_changed"),
        ("这是候选范围内最优解。", "这是全局最优解。", "scope_phrases_changed"),
    ],
)
def test_protected_field_drift_fails(
    tmp_path: Path, before: str, after: str, field: str
) -> None:
    source, output = write_pair(tmp_path, before, after)

    report = check_humanization_diff(source, output)

    assert report["status"] == "failed"
    assert report[field]


def test_typst_comments_do_not_create_false_drift(tmp_path: Path) -> None:
    source, output = write_pair(
        tmp_path,
        "正文保持 10 s。 // 内部版本 7\n",
        "正文仍为 10 s。 // 删除内部版本\n",
    )

    report = check_humanization_diff(source, output)

    assert report["status"] == "passed"
