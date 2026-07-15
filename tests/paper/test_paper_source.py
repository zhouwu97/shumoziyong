from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_paper_source import check_paper_source  # noqa: E402


def issue_codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["issues"]}  # type: ignore[index, union-attr]


def test_source_check_detects_placeholder_leak_missing_image_and_caption(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    section = tmp_path / "section.typ"
    main.write_text('#include "section.typ"\n', encoding="utf-8")
    section.write_text(
        """= 问题一
TODO：读取 results/raw.json 后待补充。
#figure(image("missing.png"))
""",
        encoding="utf-8",
    )

    report = check_paper_source(main)
    codes = issue_codes(report)

    assert report["passed"] is False
    assert "todo" in codes
    assert "internal_results_path" in codes
    assert "internal_json_name" in codes
    assert "missing_image" in codes
    assert "missing_figure_caption" in codes


def test_source_check_accepts_clean_typst_structure(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    section = tmp_path / "section.typ"
    main.write_text('#include "section.typ"\n', encoding="utf-8")
    section.write_text(
        """= 模型建立
设变量为 $x$，目标函数为
$ min x $ <eq-objective>
式 @eq-objective 给出目标函数。
#paper-figure(
  box[输入 → 求解 → 输出],
  [求解过程示意],
)
图中各步骤分别对应数据准备、模型求解与结果解释。
#three-line-table(
  [变量说明],
  (1fr, 1fr),
  ([变量], [含义]),
  (($x$, [决策变量]),),
)
""",
        encoding="utf-8",
    )

    report = check_paper_source(main)

    assert report["passed"] is True
    assert report["summary"]["failures"] == 0  # type: ignore[index]


def test_complex_block_formula_in_plain_text_fails(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    main.write_text("目标函数写作 ∑_(i=1)^n x_i = N。\n", encoding="utf-8")

    report = check_paper_source(main)

    assert report["passed"] is False
    assert "complex_formula_as_plain_text" in issue_codes(report)


def test_simple_inline_variable_does_not_trigger_formula_failure(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    main.write_text("变量 $x$ 表示设备状态。\n", encoding="utf-8")

    report = check_paper_source(main)

    assert "complex_formula_as_plain_text" not in issue_codes(report)


def test_critical_objective_formula_requires_traceable_label(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    main.write_text("目标函数为 $ max N $。\n", encoding="utf-8")

    report = check_paper_source(main)

    assert report["passed"] is False
    assert "critical_formula_missing_label" in issue_codes(report)


def test_source_check_warns_about_formulaic_language_and_lists(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    main.write_text(
        """= 分析
结果表明模型有效。
- 第一项
- 第二项
- 第三项
- 第四项
- 第五项
""",
        encoding="utf-8",
    )

    report = check_paper_source(main)
    codes = issue_codes(report)

    assert report["passed"] is True
    assert "formulaic_phrase" in codes
    assert "over_listed" in codes


def test_equation_reference_can_cross_included_files(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    model = tmp_path / "model.typ"
    discussion = tmp_path / "discussion.typ"
    main.write_text('#include "model.typ"\n#include "discussion.typ"\n', encoding="utf-8")
    model.write_text("= 模型\n$ x >= 0 $ <eq-feasible>\n", encoding="utf-8")
    discussion.write_text("= 结果\n@eq-feasible 保证解满足非负约束。\n", encoding="utf-8")

    report = check_paper_source(main)

    assert report["passed"] is True
    assert "missing_equation_label" not in issue_codes(report)
