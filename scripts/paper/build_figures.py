from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import statistics
import subprocess
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
MATLAB_SCRIPT_DIR = Path(__file__).resolve().parent / "matlab"

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Arial",
    "DejaVu Sans",
]
plt.rcParams["svg.fonttype"] = "none"
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["font.size"] = 7
plt.rcParams["axes.spines.right"] = False
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.linewidth"] = 0.8
plt.rcParams["legend.frameon"] = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 必须是对象：{path}")
    return value


def validate(payload: dict[str, Any], schema_name: str) -> None:
    schema = load_json_object(ROOT / "schemas" / schema_name)
    Draft202012Validator(schema).validate(payload)


def resolve_source_data(spec_path: Path, spec: dict[str, Any]) -> Path:
    source = (spec_path.parent / str(spec["source_data"]["path"])).resolve()
    try:
        source.relative_to(spec_path.parent.resolve())
    except ValueError as exc:
        raise ValueError("source_data 必须位于 figure spec 目录内") from exc
    if not source.is_file():
        raise FileNotFoundError(f"图表源数据不存在：{source}")
    if sha256_file(source) != spec["source_data"]["sha256"]:
        raise ValueError("图表源数据 SHA-256 与 figure spec 不一致")
    return source


def read_numeric_csv(path: Path, required_columns: list[str]) -> dict[str, list[float]]:
    columns = {column: [] for column in required_columns}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in required_columns if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV 缺少列：{', '.join(missing)}")
        for row_number, row in enumerate(reader, start=2):
            for column in required_columns:
                try:
                    value = float(str(row[column]).strip())
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"CSV 第 {row_number} 行 {column} 不是有限数值") from exc
                if not math.isfinite(value):
                    raise ValueError(f"CSV 第 {row_number} 行 {column} 不是有限数值")
                columns[column].append(value)
    if not columns[required_columns[0]]:
        raise ValueError("CSV 没有数据行")
    return columns


def calculate_statistics(
    columns: dict[str, list[float]], series: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in series:
        column = str(item["column"])
        values = columns[column]
        records.append(
            {
                "column": column,
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": statistics.fmean(values),
                "std": statistics.pstdev(values),
            }
        )
    return records


def draw_python_figure(
    spec: dict[str, Any], columns: dict[str, list[float]], output_dir: Path
) -> list[Path]:
    chart = spec["chart"]
    width = float(chart["width_mm"]) / 25.4
    height = float(chart["height_mm"]) / 25.4
    figure, axis = plt.subplots(figsize=(width, height), constrained_layout=True)
    x_values = columns[str(chart["x_column"])]
    series = chart["series"]
    chart_type = chart["type"]
    if chart_type == "grouped_bar":
        total_width = 0.78
        width_each = total_width / len(series)
        for index, item in enumerate(series):
            offset = (index - (len(series) - 1) / 2) * width_each
            positions = [value + offset for value in x_values]
            axis.bar(
                positions,
                columns[str(item["column"])],
                width=width_each,
                label=item["label"],
                color=item["color"],
                edgecolor="#272727",
                linewidth=0.6,
            )
    else:
        for item in series:
            values = columns[str(item["column"])]
            if chart_type == "line":
                axis.plot(
                    x_values,
                    values,
                    label=item["label"],
                    color=item["color"],
                    marker=item["marker"],
                    linestyle=item["line_style"],
                    linewidth=1.4,
                    markersize=3.8,
                )
            else:
                axis.scatter(
                    x_values,
                    values,
                    label=item["label"],
                    color=item["color"],
                    marker=item["marker"],
                    s=18,
                )
    axis.set_xlabel(chart["x_label"])
    axis.set_ylabel(chart["y_label"])
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.5, alpha=0.75)
    axis.legend()

    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / str(spec["export"]["output_stem"])
    outputs: list[Path] = []
    for format_name in spec["export"]["formats"]:
        target = base.with_suffix(f".{format_name}")
        dpi = int(spec["export"]["dpi"]) if format_name in {"tiff", "png"} else None
        figure.savefig(target, dpi=dpi, bbox_inches="tight", facecolor="white")
        outputs.append(target)
    plt.close(figure)
    return outputs


def output_records(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {"path": path.name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for path in paths
    ]


def matlab_quote(path: Path) -> str:
    return str(path.resolve()).replace("'", "''").replace("\\", "/")


def run_matlab_validation(spec_path: Path, output_dir: Path) -> tuple[dict[str, Any], list[str]]:
    executable = shutil.which("matlab")
    if not executable:
        return {}, ["MATLAB 不可用，无法执行独立复算"]
    expression = (
        f"addpath('{matlab_quote(MATLAB_SCRIPT_DIR)}');"
        f"render_validation_plot('{matlab_quote(spec_path)}','{matlab_quote(output_dir)}')"
    )
    completed = subprocess.run(
        [executable, "-batch", expression],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return {}, [f"MATLAB 验证失败：{completed.stderr.strip() or completed.stdout.strip()}"]
    report_path = output_dir / "matlab_validation.json"
    if not report_path.is_file():
        return {}, ["MATLAB 未生成 matlab_validation.json"]
    return load_json_object(report_path), []


def compare_statistics(
    python_stats: list[dict[str, Any]], matlab_stats: list[dict[str, Any]]
) -> tuple[float | None, list[str]]:
    matlab_by_column = {str(item["column"]): item for item in matlab_stats}
    differences: list[float] = []
    issues: list[str] = []
    for python_item in python_stats:
        column = str(python_item["column"])
        matlab_item = matlab_by_column.get(column)
        if matlab_item is None:
            issues.append(f"MATLAB 统计缺少序列：{column}")
            continue
        if int(python_item["count"]) != int(matlab_item["count"]):
            issues.append(f"Python/MATLAB 样本量不一致：{column}")
        for field in ("min", "max", "mean", "std"):
            differences.append(abs(float(python_item[field]) - float(matlab_item[field])))
    extra = set(matlab_by_column) - {str(item["column"]) for item in python_stats}
    issues.extend(f"MATLAB 统计包含未声明序列：{column}" for column in sorted(extra))
    return (max(differences) if differences else None), issues


def build_figure(spec_path: Path, output_dir: Path) -> dict[str, Any]:
    spec = load_json_object(spec_path)
    validate(spec, "paper_figure_spec.schema.json")
    source = resolve_source_data(spec_path, spec)
    required_columns = [str(spec["chart"]["x_column"])] + [
        str(item["column"]) for item in spec["chart"]["series"]
    ]
    columns = read_numeric_csv(source, required_columns)
    python_stats = calculate_statistics(columns, spec["chart"]["series"])
    python_outputs = draw_python_figure(spec, columns, output_dir)

    matlab_enabled = bool(spec["matlab_validation"]["enabled"])
    matlab_payload: dict[str, Any] = {}
    matlab_issues: list[str] = []
    max_difference: float | None = None
    matlab_status = "not_run"
    matlab_outputs: list[dict[str, Any]] = []
    matlab_stats: list[dict[str, Any]] = []
    if matlab_enabled:
        matlab_payload, matlab_issues = run_matlab_validation(spec_path, output_dir)
        if matlab_payload:
            if matlab_payload.get("source_data_sha256") != sha256_file(source):
                matlab_issues.append("MATLAB 回传的源数据 SHA-256 与 figure spec 不一致")
            matlab_stats = list(matlab_payload.get("statistics", []))
            max_difference, comparison_issues = compare_statistics(python_stats, matlab_stats)
            matlab_issues.extend(comparison_issues)
            for name in matlab_payload.get("outputs", []):
                path = output_dir / str(name)
                if path.is_file():
                    matlab_outputs.extend(output_records([path]))
                else:
                    matlab_issues.append(f"MATLAB 声明的输出不存在：{name}")
            tolerance = float(spec["matlab_validation"]["tolerance"])
            if max_difference is not None and max_difference > tolerance:
                matlab_issues.append(
                    f"Python/MATLAB 最大统计差 {max_difference:.6g} 超过容差 {tolerance:.6g}"
                )
        matlab_status = "failed" if matlab_issues else "passed"

    report = {
        "schema_version": "1.0.0",
        "figure_id": spec["figure_id"],
        "backend": "python",
        "core_conclusion": spec["core_conclusion"],
        "source_data_sha256": sha256_file(source),
        "outputs": output_records(python_outputs),
        "python_statistics": python_stats,
        "matlab_validation": {
            "enabled": matlab_enabled,
            "status": matlab_status,
            "outputs": matlab_outputs,
            "statistics": matlab_stats,
            "max_abs_difference": max_difference,
            "issues": matlab_issues,
        },
        "status": "failed" if matlab_enabled and matlab_status != "passed" else "passed",
    }
    validate(report, "paper_figure_build_report.schema.json")
    report_path = output_dir / "figure_build_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="构建 Python 投稿图并执行 MATLAB 独立复算")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_figure(args.spec, args.output_dir)
    print(
        json.dumps(
            {
                "status": report["status"],
                "outputs": len(report["outputs"]),
                "matlab": report["matlab_validation"]["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
