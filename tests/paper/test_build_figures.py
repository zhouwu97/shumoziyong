from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from build_figures import build_figure, compare_statistics, sha256_file  # noqa: E402


def make_spec(tmp_path: Path, *, matlab_enabled: bool) -> Path:
    data_path = tmp_path / "source_data.csv"
    data_path.write_text("budget,method,baseline\n1,10,8\n2,13,9\n3,15,11\n", encoding="utf-8")
    spec = {
        "schema_version": "1.0.0",
        "figure_id": "fig_budget_comparison",
        "core_conclusion": "候选方法在三个预算水平下均保持更高的完成量",
        "archetype": "quantitative_grid",
        "purpose": "比较候选方法与同配置基线随预算变化的完成量",
        "claim_ids": ["C001"],
        "source_data": {"path": "source_data.csv", "sha256": sha256_file(data_path)},
        "chart": {
            "type": "line",
            "x_column": "budget",
            "series": [
                {
                    "column": "method",
                    "label": "候选方法",
                    "color": "#0F4D92",
                    "marker": "o",
                    "line_style": "-",
                },
                {
                    "column": "baseline",
                    "label": "同配置基线",
                    "color": "#767676",
                    "marker": "s",
                    "line_style": "--",
                },
            ],
            "x_label": "预算水平",
            "y_label": "完成量（件）",
            "width_mm": 89,
            "height_mm": 62,
        },
        "statistics": {
            "n_definition": "每个序列包含三个预算水平",
            "center_statistic": "图中展示各预算水平的正式结果",
            "spread": "本示例无重复试验误差条",
            "baseline_definition": "相同配置、参数和时间范围下的基线策略",
        },
        "export": {
            "output_stem": "budget_comparison",
            "formats": ["svg", "pdf", "tiff", "png"],
            "dpi": 600,
        },
        "matlab_validation": {"enabled": matlab_enabled, "tolerance": 1e-12},
        "review_risks": ["样本量较小，正文不得外推到未测试预算"],
    }
    spec_path = tmp_path / "figure_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec_path


def test_python_publication_build_exports_editable_bundle(tmp_path: Path) -> None:
    spec_path = make_spec(tmp_path, matlab_enabled=False)
    output_dir = tmp_path / "outputs"

    report = build_figure(spec_path, output_dir)

    assert report["status"] == "passed"
    assert {Path(item["path"]).suffix for item in report["outputs"]} == {
        ".svg",
        ".pdf",
        ".tiff",
        ".png",
    }
    svg = (output_dir / "budget_comparison.svg").read_text(encoding="utf-8")
    assert "<text" in svg
    assert report["matlab_validation"]["status"] == "not_run"


def test_source_data_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    spec_path = make_spec(tmp_path, matlab_enabled=False)
    (tmp_path / "source_data.csv").write_text("budget,method,baseline\n1,99,8\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        build_figure(spec_path, tmp_path / "outputs")


def test_statistics_comparison_reports_maximum_difference() -> None:
    python_stats = [{"column": "value", "count": 2, "min": 1, "max": 3, "mean": 2, "std": 1}]
    matlab_stats = [
        {"column": "value", "count": 2, "min": 1, "max": 3, "mean": 2.01, "std": 1}
    ]

    difference, issues = compare_statistics(python_stats, matlab_stats)

    assert difference == pytest.approx(0.01)
    assert issues == []


@pytest.mark.skipif(shutil.which("matlab") is None, reason="MATLAB runtime not installed")
def test_matlab_independent_validation_matches_python(tmp_path: Path) -> None:
    spec_path = make_spec(tmp_path, matlab_enabled=True)
    output_dir = tmp_path / "outputs"

    report = build_figure(spec_path, output_dir)

    assert report["status"] == "passed"
    assert report["matlab_validation"]["status"] == "passed"
    assert report["matlab_validation"]["max_abs_difference"] <= 1e-12
    assert (output_dir / "budget_comparison_matlab_validation.png").is_file()
    assert (output_dir / "budget_comparison_matlab_validation.fig").is_file()
