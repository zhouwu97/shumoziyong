"""构建 2024-C v2.1 Gate 4 论文、图表和 Claim-Evidence 工件。

正式图表仅由 Python 生成。脚本只读取当前运行内已经验证的结果，
不会重新求解模型，也不会把 MATLAB A+B 表述为完整模型独立复现。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


SCENARIO_LABELS = {
    "q1_waste": "Q1 超产滞销",
    "q1_discount": "Q1 超产折价",
    "q2_frozen": "Q2 保守路径",
    "q3_frozen": "Q3 受控代理",
}
SCENARIO_COLORS = {
    "q1_waste": "#2B6F8A",
    "q1_discount": "#C46A2B",
    "q2_frozen": "#3D7D5C",
    "q3_frozen": "#7A5C8E",
}
RUN_ID = "2024C_v21_full_replay_20260715"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_ref(run_dir: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(run_dir.resolve()).as_posix(),
        "sha256": sha256_file(path),
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Noto Sans SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def save_figure(fig: plt.Figure, output_base: Path) -> dict[str, Any]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    exports: dict[str, Path] = {}
    for suffix in ("svg", "pdf", "tiff", "png"):
        path = output_base.with_suffix(f".{suffix}")
        dpi = 450 if suffix in {"tiff", "png"} else 300
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
        exports[suffix] = path
    plt.close(fig)

    checks: list[dict[str, Any]] = []
    status = "passed"
    for suffix, path in exports.items():
        check: dict[str, Any] = {
            "format": suffix,
            "size_bytes": path.stat().st_size,
            "passed": path.stat().st_size > 1000,
        }
        if suffix in {"png", "tiff"}:
            with Image.open(path) as image:
                gray = np.asarray(image.convert("L"), dtype=float)
                check.update(
                    {
                        "width": image.width,
                        "height": image.height,
                        "pixel_std": float(gray.std()),
                        "nonwhite_fraction": float(np.mean(gray < 248)),
                    }
                )
                check["passed"] = bool(
                    check["passed"]
                    and image.width >= 1800
                    and image.height >= 900
                    and gray.std() > 8
                    and np.mean(gray < 248) > 0.02
                )
        if not check["passed"]:
            status = "failed"
        checks.append(check)
    qa = {
        "schema_version": "1.0.0",
        "figure_id": output_base.name,
        "status": status,
        "checks": checks,
        "visual_contract": {
            "blank_canvas_rejected": True,
            "minimum_raster_width": 1800,
            "minimum_raster_height": 900,
            "python_backend_only": True,
        },
    }
    qa_path = output_base.with_suffix(".qa.json")
    write_json(qa_path, qa)
    if status != "passed":
        raise ValueError(f"图表 QA 未通过：{qa_path}")
    return {"exports": exports, "qa_path": qa_path}


def source_attestation(
    run_dir: Path,
    source_path: Path,
    attestation_path: Path,
    derived_from: Iterable[Path],
) -> dict[str, Any]:
    source_ref = file_ref(run_dir, source_path)
    value = {
        "schema_version": "1.0.0",
        "artifact_type": "figure_source_data_attestation",
        "run_id": RUN_ID,
        "status": "verified",
        "source_data_ref": source_ref,
        "derived_from": [file_ref(run_dir, path) for path in derived_from],
        "formal_result_activation_status": "run_execution_verified",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "仅用于当前论文图表，不改变 Formal Result。",
    }
    write_json(attestation_path, value)
    return value


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_figure_1(run_dir: Path, script_copy: Path) -> dict[str, Any]:
    summary_path = run_dir / "workspace/results/result_summary.json"
    summary = read_json(summary_path)
    rows: list[dict[str, Any]] = []
    for scenario in SCENARIO_LABELS:
        item = summary["scenario_summary"][scenario]
        for year, yearly in item["yearly"].items():
            rows.append(
                {
                    "scenario": scenario,
                    "scenario_label": SCENARIO_LABELS[scenario],
                    "year": int(year),
                    "yearly_profit_yuan": yearly["profit"],
                    "total_profit_yuan": item["objective_recomputed"],
                    "mip_gap": item["solver"]["mip_gap"],
                    "constraint_feasible": item["validator"]["feasible"],
                }
            )
    source = run_dir / "paper/source_data/figure_01_scenario_profit.csv"
    write_csv(
        source,
        [
            "scenario",
            "scenario_label",
            "year",
            "yearly_profit_yuan",
            "total_profit_yuan",
            "mip_gap",
            "constraint_feasible",
        ],
        rows,
    )
    attestation_path = source.with_suffix(".attestation.json")
    source_attestation(
        run_dir,
        source,
        attestation_path,
        [summary_path, run_dir / "workspace/results/formal_result.json", run_dir / "result_report.json"],
    )

    configure_matplotlib()
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.0), constrained_layout=True)
    scenarios = list(SCENARIO_LABELS)
    totals = [summary["scenario_summary"][key]["objective_recomputed"] / 1e6 for key in scenarios]
    bars = axes[0].barh(
        np.arange(len(scenarios)),
        totals,
        color=[SCENARIO_COLORS[key] for key in scenarios],
        edgecolor="#25313A",
        linewidth=0.5,
    )
    axes[0].set_yticks(np.arange(len(scenarios)), [SCENARIO_LABELS[key] for key in scenarios])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("2024-2030 年累计利润（百万元）")
    axes[0].set_title("a  不同经济口径下的时限内可行方案")
    axes[0].grid(axis="x", color="#D9DEE5", linewidth=0.6)
    axes[0].spines[["top", "right", "left"]].set_visible(False)
    for bar, total, key in zip(bars, totals, scenarios):
        gap = summary["scenario_summary"][key]["solver"]["mip_gap"]
        axes[0].text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{total:.2f}  | gap={gap:.3f}",
            va="center",
            fontsize=7.5,
        )
    for key in scenarios:
        yearly = summary["scenario_summary"][key]["yearly"]
        years = np.array([int(year) for year in yearly])
        values = np.array([yearly[str(year)]["profit"] / 1e6 for year in years])
        style = "--" if key == "q3_frozen" else "-"
        axes[1].plot(
            years,
            values,
            marker="o",
            markersize=3.5,
            linewidth=1.7,
            linestyle=style,
            color=SCENARIO_COLORS[key],
            label=SCENARIO_LABELS[key],
        )
    axes[1].set_title("b  年度利润轨迹")
    axes[1].set_xlabel("年份")
    axes[1].set_ylabel("年度利润（百万元）")
    axes[1].grid(color="#D9DEE5", linewidth=0.6)
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].legend(frameon=False, ncol=2, loc="upper center")
    axes[1].annotate(
        "Q3 最终复用 Q2，曲线完全重合",
        xy=(2029, summary["scenario_summary"]["q2_frozen"]["yearly"]["2029"]["profit"] / 1e6),
        xytext=(2026.0, 4.3),
        arrowprops={"arrowstyle": "->", "color": "#59636D", "lw": 0.8},
        fontsize=7.5,
        color="#303840",
    )
    output = run_dir / "paper/figures/figure_01_scenario_profit"
    saved = save_figure(fig, output)
    caption = (
        "图 1｜四类情形的累计利润与年度轨迹。左图报告统一评价器复算的时限内可行方案，"
        "并逐项披露非零 MIP gap；不同销售口径不可解释为同一目标下的算法改进。"
        "右图显示 Q3 经 dominance guard 后复用 Q2，因此两条曲线完全重合。"
    )
    caption_path = output.with_suffix(".caption.md")
    caption_path.write_text(caption + "\n", encoding="utf-8")
    fragment = {
        "figure_id": output.name,
        "core_conclusion": "超产折价规则显著改变利润口径，而 Q3 受控代理没有产生优于 Q2 的方案。",
        "evidence_chain": ["C001", "C002", "C003", "C004", "result_report.json#/metrics"],
        "archetype": "quantitative_grid",
        "source_data_ref": file_ref(run_dir, source),
        "source_data_attestation_ref": file_ref(run_dir, attestation_path),
        "script_ref": file_ref(run_dir, script_copy),
        "exports": {key: file_ref(run_dir, path) for key, path in saved["exports"].items() if key != "png"},
        "qa_ref": file_ref(run_dir, saved["qa_path"]),
    }
    write_json(output.with_suffix(".fragment.json"), fragment)
    return fragment


def build_figure_2(run_dir: Path, script_copy: Path, final: bool) -> dict[str, Any]:
    original = run_dir / "workspace/results/q3_sample_profits.csv"
    source = run_dir / "paper/source_data/figure_02_risk_samples.csv"
    shutil.copy2(original, source)
    metrics_path = run_dir / "workspace/results/q3_risk_metrics.json"
    attestation_path = source.with_suffix(".attestation.json")
    source_attestation(
        run_dir,
        source,
        attestation_path,
        [original, metrics_path, run_dir / "workspace/results/formal_result.json"],
    )
    rows = list(csv.DictReader(source.read_text(encoding="utf-8-sig").splitlines()))
    data: dict[tuple[str, str], np.ndarray] = {}
    for regime in ("correlated", "independent"):
        for strategy in ("q2_frozen", "q3_frozen"):
            data[(regime, strategy)] = np.array(
                [float(row["profit_yuan"]) / 1e6 for row in rows if row["regime"] == regime and row["strategy"] == strategy]
            )

    configure_matplotlib()
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.0), constrained_layout=True)
    positions = [1, 2]
    q2_values = [data[("correlated", "q2_frozen")], data[("independent", "q2_frozen")]]
    violins = axes[0].violinplot(q2_values, positions=positions, widths=0.72, showmeans=False, showextrema=False)
    for body, color in zip(violins["bodies"], ["#5B7F95", "#6F8F72"]):
        body.set_facecolor(color)
        body.set_edgecolor("#25313A")
        body.set_alpha(0.75)
    for pos, values in zip(positions, q2_values):
        q05, median, q95 = np.quantile(values, [0.05, 0.5, 0.95])
        axes[0].plot([pos, pos], [q05, q95], color="#20272D", lw=1.4)
        axes[0].scatter([pos], [median], color="white", edgecolor="#20272D", s=28, zorder=3)
    axes[0].set_xticks(positions, ["相关假设", "独立假设"])
    axes[0].set_ylabel("七年模拟利润（百万元）")
    axes[0].set_title("a  Q2 固定方案的外样本风险分布")
    axes[0].grid(axis="y", color="#D9DEE5", linewidth=0.6)
    axes[0].spines[["top", "right"]].set_visible(False)

    corr_diff = data[("correlated", "q3_frozen")] - data[("correlated", "q2_frozen")]
    ind_diff = data[("independent", "q3_frozen")] - data[("independent", "q2_frozen")]
    if final:
        metrics = read_json(metrics_path)["risk_metrics"]
        names = ["标准差", "均值-P05", "均值-CVaR05"]
        correlated = metrics["q2_frozen_correlated"]
        independent = metrics["q2_frozen_independent"]
        corr_values = np.array(
            [
                correlated["std"],
                correlated["mean"] - correlated["p05"],
                correlated["mean"] - correlated["cvar05"],
            ]
        ) / 1e4
        ind_values = np.array(
            [
                independent["std"],
                independent["mean"] - independent["p05"],
                independent["mean"] - independent["cvar05"],
            ]
        ) / 1e4
        x = np.arange(len(names))
        width = 0.34
        axes[1].bar(x - width / 2, corr_values, width, color="#5B7F95", label="相关假设")
        axes[1].bar(x + width / 2, ind_values, width, color="#6F8F72", label="独立假设")
        axes[1].set_xticks(x, names)
        axes[1].set_ylabel("风险尺度（万元）")
        axes[1].set_title("b  两类分布假设的下行风险尺度")
        axes[1].legend(frameon=False)
        axes[1].text(
            0.5,
            0.96,
            "Q3=Q2；两种制度下配对均值改进均为 0 元",
            transform=axes[1].transAxes,
            ha="center",
            va="top",
            fontsize=7.5,
            color="#40484F",
        )
    else:
        axes[1].bar([0, 1], [corr_diff.mean(), ind_diff.mean()], color=["#7A5C8E", "#A37A54"], width=0.58)
        axes[1].axhline(0, color="#20272D", linewidth=0.9)
        axes[1].set_xticks([0, 1], ["相关假设", "独立假设"])
        axes[1].set_ylabel("Q3-Q2 配对均值差（元）")
        axes[1].set_title("b  Q3 相对 Q2 的配对改进")
        axes[1].set_ylim(-1, 1)
        for x in (0, 1):
            axes[1].text(x, 0.08, "0 元", ha="center", va="bottom", fontsize=8)
        axes[1].text(
            0.5,
            -0.72,
            "最终 Q3 方案与 Q2 相同；相关结构仅为预注册模拟假设",
            ha="center",
            fontsize=7.5,
            color="#40484F",
        )
    axes[1].grid(axis="y", color="#D9DEE5", linewidth=0.6)
    axes[1].spines[["top", "right"]].set_visible(False)
    output = run_dir / "paper/figures/figure_02_risk_comparison"
    saved = save_figure(fig, output)
    caption = (
        "图 2｜Q2/Q3 的风险评估。相关与独立样本各 2000 组；左图仅描述预注册分布假设内的"
        "Q2 固定方案风险，不代表真实概率分布的外部估计。Q3 最终方案与 Q2 完全相同，"
        "所以两种样本制度下的配对均值改进均为 0。"
    )
    output.with_suffix(".caption.md").write_text(caption + "\n", encoding="utf-8")
    fragment = {
        "figure_id": output.name,
        "core_conclusion": "在预注册相关与独立样本下，Q3 最终方案相对 Q2 的配对均值改进均为零。",
        "evidence_chain": ["C004", "C007", "workspace/results/q3_risk_metrics.json"],
        "archetype": "quantitative_grid",
        "source_data_ref": file_ref(run_dir, source),
        "source_data_attestation_ref": file_ref(run_dir, attestation_path),
        "script_ref": file_ref(run_dir, script_copy),
        "exports": {key: file_ref(run_dir, path) for key, path in saved["exports"].items() if key != "png"},
        "qa_ref": file_ref(run_dir, saved["qa_path"]),
    }
    write_json(output.with_suffix(".fragment.json"), fragment)
    return fragment


def build_figure_3(run_dir: Path, script_copy: Path) -> dict[str, Any]:
    original = run_dir / "workspace/tables/table4_sensitivity.csv"
    source = run_dir / "paper/source_data/figure_03_sensitivity.csv"
    shutil.copy2(original, source)
    sensitivity_path = run_dir / "workspace/results/sensitivity_results.json"
    attestation_path = source.with_suffix(".attestation.json")
    source_attestation(
        run_dir,
        source,
        attestation_path,
        [original, sensitivity_path, run_dir / "model_validity_report.json"],
    )
    rows = list(csv.DictReader(source.read_text(encoding="utf-8-sig").splitlines()))
    labels = [row["parameter_case"] for row in rows]
    changes = np.array([float(row["relative_change"]) * 100 for row in rows])
    objectives = np.array([float(row["objective"]) / 1e6 for row in rows])

    configure_matplotlib()
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.0), constrained_layout=True)
    colors = ["#B85C4A" if value < 0 else "#3D7D5C" for value in changes]
    bars = axes[0].barh(np.arange(len(labels)), changes, color=colors, edgecolor="#25313A", linewidth=0.4)
    axes[0].set_yticks(np.arange(len(labels)), labels)
    axes[0].invert_yaxis()
    axes[0].axvline(0, color="#20272D", linewidth=0.8)
    axes[0].axvline(-5, color="#9AA2A9", linewidth=0.7, linestyle="--")
    axes[0].axvline(5, color="#9AA2A9", linewidth=0.7, linestyle="--")
    axes[0].set_xlabel("固定方案利润相对变化（%）")
    axes[0].set_title("a  单因素 ±5% 敏感性")
    axes[0].grid(axis="x", color="#D9DEE5", linewidth=0.6)
    axes[0].spines[["top", "right", "left"]].set_visible(False)
    for bar, value in zip(bars, changes):
        align = "left" if value >= 0 else "right"
        offset = 0.12 if value >= 0 else -0.12
        axes[0].text(value + offset, bar.get_y() + bar.get_height() / 2, f"{value:.2f}%", va="center", ha=align, fontsize=7.5)

    axes[1].scatter(changes, objectives, s=52, c=colors, edgecolor="#25313A", linewidth=0.5)
    for x, y, label in zip(changes, objectives, labels):
        axes[1].annotate(label, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7)
    axes[1].axvline(0, color="#20272D", linewidth=0.8)
    axes[1].set_xlabel("利润相对变化（%）")
    axes[1].set_ylabel("扰动后七年利润（百万元）")
    axes[1].set_title("b  扰动方向与利润水平")
    axes[1].grid(color="#D9DEE5", linewidth=0.6)
    axes[1].spines[["top", "right"]].set_visible(False)
    output = run_dir / "paper/figures/figure_03_sensitivity"
    saved = save_figure(fig, output)
    caption = (
        "图 3｜Q2 固定方案的局部敏感性。所有结果均为固定方案后评估，未在扰动参数下重新优化；"
        "六项 ±5% 扰动的利润绝对变化均不超过 4.68%，其中亩产下降最敏感。"
    )
    output.with_suffix(".caption.md").write_text(caption + "\n", encoding="utf-8")
    fragment = {
        "figure_id": output.name,
        "core_conclusion": "Q2 固定方案在六项单因素扰动下的利润绝对变化不超过 4.68%，亩产下降最敏感。",
        "evidence_chain": ["C006", "model_validity_report.json#/parameter_stability"],
        "archetype": "quantitative_grid",
        "source_data_ref": file_ref(run_dir, source),
        "source_data_attestation_ref": file_ref(run_dir, attestation_path),
        "script_ref": file_ref(run_dir, script_copy),
        "exports": {key: file_ref(run_dir, path) for key, path in saved["exports"].items() if key != "png"},
        "qa_ref": file_ref(run_dir, saved["qa_path"]),
    }
    write_json(output.with_suffix(".fragment.json"), fragment)
    return fragment


def build_claim_map(run_dir: Path, final: bool) -> dict[str, Any]:
    claims = [
        {
            "claim_id": "C001",
            "claim": "Q1 超产滞销情形的七年累计复算利润为 17307953.25 元。",
            "scope": "仅覆盖当前官方材料、价格中点口径和 60 秒求解时限内的约束可行方案。",
            "result_refs": ["result_report.json#/metrics/0"],
            "evidence_refs": ["workspace/results/formal_result.json#/scenarios/0", "matlab_level_a_report.json#/checks/0"],
            "figure_refs": ["paper/figures/figure_01_scenario_profit.pdf"],
            "manuscript_locations": ["结果/问题一"],
            "status": "bounded_inference",
        },
        {
            "claim_id": "C002",
            "claim": "Q1 超产折价情形的七年累计复算利润为 54065488.29 元。",
            "scope": "利润提高来自销售规则变化，不解释为同一目标函数下的算法改进或全局最优。",
            "result_refs": ["result_report.json#/metrics/1"],
            "evidence_refs": ["workspace/results/formal_result.json#/scenarios/1", "matlab_level_a_report.json#/checks/4"],
            "figure_refs": ["paper/figures/figure_01_scenario_profit.pdf"],
            "manuscript_locations": ["结果/问题一"],
            "status": "bounded_inference",
        },
        {
            "claim_id": "C003",
            "claim": "Q2 保守参数路径的七年累计复算利润为 17224619.36 元。",
            "scope": "该数值对应预先冻结的保守路径，不是随机参数真实期望的无偏估计。",
            "result_refs": ["result_report.json#/metrics/2"],
            "evidence_refs": ["workspace/results/formal_result.json#/scenarios/2", "matlab_level_a_report.json#/checks/8"],
            "figure_refs": ["paper/figures/figure_01_scenario_profit.pdf"],
            "manuscript_locations": ["结果/问题二"],
            "status": "bounded_inference",
        },
        {
            "claim_id": "C004",
            "claim": "Q3 最终方案经 dominance guard 后复用 Q2，七年复算利润同为 17224619.36 元。",
            "scope": "完整 240 场景 SAA 未获得整数可行解，结论只覆盖均值代理与回退规则。",
            "result_refs": ["result_report.json#/metrics/3"],
            "evidence_refs": ["workspace/results/result_summary.json#/scenario_summary/q3_frozen/solver", "matlab_level_a_report.json#/checks/12"],
            "figure_refs": ["paper/figures/figure_01_scenario_profit.pdf", "paper/figures/figure_02_risk_comparison.pdf"],
            "manuscript_locations": ["结果/问题三"],
            "status": "bounded_inference",
        },
        {
            "claim_id": "C005",
            "claim": "四个正式情形的独立约束复算均未发现超过容差的约束违反。",
            "scope": "证明当前导出方案满足已实现约束，不证明题意建模无遗漏或求解达到全局最优。",
            "result_refs": ["result_report.json#/metrics/5"],
            "evidence_refs": ["validation/report.json", "matlab_level_a_report.json"],
            "manuscript_locations": ["模型检验/可行性"],
            "status": "supported",
        },
        {
            "claim_id": "C006",
            "claim": "Q2 固定方案在六项单因素正负 5% 扰动下的利润绝对变化不超过 4.68%。",
            "scope": "这是固定方案后评估，未在每个扰动场景中重新优化种植结构。",
            "result_refs": ["result_report.json#/metrics/6"],
            "evidence_refs": ["workspace/results/sensitivity_results.json", "model_validity_report.json#/parameter_stability"],
            "figure_refs": ["paper/figures/figure_03_sensitivity.pdf"],
            "manuscript_locations": ["敏感性分析"],
            "status": "bounded_inference",
        },
        {
            "claim_id": "C007",
            "claim": "相关与独立样本制度下，Q3 相对 Q2 的配对均值利润改进均为 0 元。",
            "scope": "相关结构为预注册模拟假设，风险数字不代表真实分布的外部统计估计。",
            "result_refs": ["result_report.json#/metrics/7"],
            "evidence_refs": ["workspace/results/q3_risk_metrics.json", "workspace/results/q3_sample_profits.csv"],
            "figure_refs": ["paper/figures/figure_02_risk_comparison.pdf"],
            "manuscript_locations": ["结果/问题三"],
            "status": "bounded_inference",
        },
    ]
    value = {
        "schema_version": "2.0.0",
        "artifact_type": "paper_claim_map_v2",
        "run_id": RUN_ID,
        "problem_id": "2024-C",
        "claims": claims,
    }
    target = run_dir / "paper_claim_map.json"
    write_json(target, value)
    if not final:
        archive = run_dir / "paper/archive/paper_claim_map_round1.json"
        write_json(archive, value)
    return value


def write_terminology(run_dir: Path) -> None:
    text = """# Terminology Ledger

| 术语 | 固定含义 | 禁止替换或扩大 |
|---|---|---|
| 时限内可行方案 | 在预设求解时限内获得、并通过约束复算的方案 | 不写成最优解、全局最优解 |
| 超产滞销 | 超过预期销售量的产量不产生销售收入 | 不等同于产量报废成本 |
| 超产折价 | 超过预期销售量的产量按正常价格的 50% 销售 | 不写成算法收益提升 |
| Q2 保守路径 | 对题面变化范围采用冻结的保守参数路径 | 不写成真实期望或概率预测 |
| Q3 受控代理 | 相关样本均值参数代理 MILP 加 dominance guard | 不写成完整 SAA 解 |
| 相关样本 | 按预注册系数生成的模拟相关结构 | 不写成从官方数据识别的真实相关性 |
| MATLAB Level A | 从官方输入和最终决策向量独立复算目标、残差和统计量 | 不写成完整模型独立求解 |
| MATLAB Level B | 对冻结合同的小样例独立建模求解 | 不写成完整规模复现 |
| 固定方案敏感性 | 固定种植结构后改变单个参数并重新评价 | 不写成扰动后重新优化 |
| development integration benchmark | 用于检验工作流集成与回归的开发基准 | 不写成陌生题盲测泛化证据 |
"""
    path = run_dir / "paper/terminology_ledger.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    (run_dir / "paper/one_sentence_argument.md").write_text(
        "在严格区分可行性、最优性与分布假设的前提下，分段收入混合整数规划能够给出可复算的多期种植方案，但本次 Q3 随机代理并未带来超过 Q2 的收益。\n",
        encoding="utf-8",
    )


def manuscript_text(final: bool, figure_prefix: str) -> str:
    boundary = """
#block(fill: rgb("f4f6f7"), inset: 10pt, radius: 3pt)[
*结论边界。* 全文中的“方案”均指时限内约束可行方案。四个主情形的 MIP gap 均非零，
因此不宣称全局最优；Q3 相关系数是预注册模拟假设；MATLAB Level A+B 不是完整模型独立复现。
]
""" if final else ""
    bean_note = (
        "实现中将‘任意连续三年内种植过豆类’操作化为三年豆类累计面积不少于整块地面积。"
        "该约束比仅要求出现一次豆类更强，换取了可检查的覆盖强度，也可能压缩可行域；故其影响属于模型假设而非题面事实。"
    ) if final else "三年窗口内设置豆类覆盖约束。"
    result_boundary = (
        "表中 gap 为求解器报告的相对 MIP gap，数值未关闭；因此利润只用于比较已获得可行方案，"
        "不用于证明任一情形达到全局最优。Q1 两列对应不同销售规则，不能把折价情形的高利润解释为算法改进。"
    ) if final else "四个方案均通过约束复算。"
    q3_boundary = (
        "相关结构仅用于情景压力测试，不是从官方附件识别的统计规律。由于 dominance guard 选择了 Q2 方案，"
        "Q3 与 Q2 的全部样本利润逐一相同，故配对均值差和改进概率分别为 0 元和 0。"
    ) if final else "Q3 最终复用 Q2，配对均值差为 0。"

    template = r'''#set page(paper: "a4", margin: (x: 2.2cm, y: 2cm), numbering: "1")
#set text(font: ("Noto Serif SC", "Source Han Serif SC"), size: 10pt, lang: "zh")
#set par(justify: true, leading: 0.72em, first-line-indent: 2em)
#set heading(numbering: "1.")
#show heading.where(level: 1): it => block(above: 13pt, below: 7pt)[#set text(size: 13pt, weight: "bold"); #it]
#show heading.where(level: 2): it => block(above: 10pt, below: 5pt)[#set text(size: 11pt, weight: "bold"); #it]
#show figure.caption: set text(size: 8.5pt)

#align(center)[
  #text(size: 18pt, weight: "bold")[面向多期轮作与销售不确定性的农作物种植策略]
  #v(4pt)
  #text(size: 12pt)[可复算混合整数规划与受限随机评估]
]

#v(8pt)
#text(weight: "bold")[摘要：]
针对 2024—2030 年多地块、多季次农作物种植决策，本文建立含连续面积变量与二元启用变量的分段收入混合整数规划。
模型统一处理地块容量、作物适配、水浇地种植模式、相邻年度重茬、滚动三年豆类覆盖、最小种植面积与种植分散度。
问题一分别刻画超产滞销和超产半价销售；问题二采用题面变化范围内的冻结保守路径；问题三先尝试 240 情景 SAA，
在预设时限内未获得整数可行解后，按合同降级为相关样本均值参数代理，并以 dominance guard 防止劣于 Q2 的候选进入正式结果。
统一评价器复算得到四类情形七年利润分别为 1730.80、5406.55、1722.46 和 1722.46 万元，所有导出方案的最大约束违反为 0。
Q3 最终复用 Q2，在相关与独立样本下的配对均值改进均为 0；Q2 固定方案在六项正负 5% 扰动下的最大利润绝对变化为 4.68%。
Python 与 MATLAB Level A 的目标复算在 1e-4 元容差内一致，Level B 的轮作与零收益小样例全部通过。
本文据此给出可执行种植方案，同时明确非零 MIP gap、相关假设不可识别和完整 SAA 未完成所限定的结论范围。

#text(weight: "bold")[关键词：] 多期种植；混合整数规划；轮作约束；情景模拟；敏感性分析；跨语言复算

__BOUNDARY__

= 问题重述与分析

乡村现有露天耕地、水浇地和温室在面积、适合作物及可用季次上存在差异。决策者需要安排 2024—2030 年各地块各季次的作物与面积，
同时避免连续重茬、满足豆类轮作要求并控制种植过度分散。销售端又存在产量超过预期销售量后的处理差异，未来亩产、成本、价格和需求亦具有不确定性。

四个计算任务具有共同的跨期资源配置骨架。问题一改变超产收入函数；问题二把题面给出的变化范围冻结为透明的保守参数路径；
问题三需要区分“边际变化范围”与“变量相关结构”：前者来自题面，后者无法由附件识别，只能作为外生假设进行压力测试。
因此本文先冻结统一评价函数和约束，再比较确定性、保守路径与受控随机代理，避免不同程序之间出现口径漂移。

= 符号、数据与基本假设

记 $t in T={2024,...,2030}$ 为年份，$p in P$ 为地块，$s in S_p$ 为地块允许季次，$c in C_(p,s)$ 为允许作物。
$A_p$ 为地块面积，$y_(p,s,c)$、$k_(p,s,c)$ 和 $r_(s,c)$ 分别表示亩产、亩成本和销售单价中点，$D_(t,s,c)$ 为预期销售上限。

主要假设如下：销售价格区间取中点；2023 年实际种植与亩产用于推导销售基准和首年重茬边界；
Q2 的确定性路径用于保守决策而非概率预测；Q3 的相关系数在计算前固定，但不视为真实统计规律。

数据处理只读取官方附件。程序将地块类型、季次与作物适配关系转换为可行索引集，并核对同作物同季价格的一致性。
所有正式利润均由导出面积经过统一评价器重新计算，求解器内部目标不直接作为论文数值。

= 多期分段收入混合整数规划

== 决策变量与收入函数

令 $x_(t,p,s,c) >= 0$ 表示种植面积，$z_(t,p,s,c) in {0,1}$ 表示该组合是否启用。
令 $Q_(t,s,c)=sum_p y_(p,s,c) x_(t,p,s,c)$ 为总产量。对超产折价系数 $alpha in {0,0.5}$，收入写为

$ R_(t,s,c)(alpha) = r_(s,c) [ min(Q_(t,s,c),D_(t,s,c)) + alpha max(Q_(t,s,c)-D_(t,s,c),0) ]. $

引入正常销量辅助变量即可将分段收入线性化。目标是在给定参数路径下最大化七年利润

$ max Phi_alpha = sum_(t,s,c) R_(t,s,c)(alpha) - sum_(t,p,s,c) k_(p,s,c) x_(t,p,s,c). $

== 主要约束

地块容量约束为 $sum_c x_(t,p,s,c) <= A_p$。面积与启用变量通过
$ m_p z_(t,p,s,c) <= x_(t,p,s,c) <= A_p z_(t,p,s,c) $ 连接，其中露天地块的最小面积取地块面积的 20%，温室取 30%。

若 2023 年地块 $p$ 的季次 $s$ 已种作物 $c$，则 2024 年对应 $z$ 必须为 0；其后采用
$ z_(t,p,s,c)+z_(t+1,p,s,c) <= 1 $ 禁止相邻年度重茬。__BEAN_NOTE__

同一作物同一季次每年最多分布在 8 个地块。水浇地的单季水稻模式与两季蔬菜模式互斥；其他地块按允许季次分别实施容量约束。
这些规则均由独立 Validator 对最终面积表重新计算。

== 问题二与问题三

Q2 冻结路径取亩产系数 0.95，成本逐年乘以 1.05；小麦和玉米需求按 7.5% 年增长，蔬菜价格按 5% 年增长，
食用菌价格按题面方向下降。该路径的作用是形成可解释的保守方案，不代表未来参数的统计期望。

Q3 先用固定种子生成 240 组相关训练样本。完整 SAA-MILP 在预注册 60 秒内未得到整数可行解，
故按 Gate 1 合同降级为逐年均值参数代理 MILP。若代理候选在同一训练均值评价器下劣于 Q2，则 dominance guard 直接复用 Q2。
最终再使用 2000 组相关样本和 2000 组独立样本评价固定方案的均值、标准差、5% 分位数和 CVaR。

= 结果

== 问题一：销售规则改变利润口径

#figure(image("__FIG_PREFIX__figures/figure_01_scenario_profit.pdf", width: 100%), caption: [
四类情形的累计利润与年度轨迹。左图同时披露 MIP gap；右图中 Q3 与 Q2 完全重合。
])

#table(
  columns: (1.4fr, 1fr, 0.8fr, 0.8fr),
  inset: 5pt,
  stroke: 0.4pt + rgb("c9ced3"),
  [*情形*], [*七年利润/万元*], [*MIP gap*], [*最大违反/亩*],
  [Q1 超产滞销], [1730.80], [1.3807], [0],
  [Q1 超产折价], [5406.55], [0.0976], [0],
  [Q2 保守路径], [1722.46], [1.3996], [0],
  [Q3 受控代理], [1722.46], [1.4338], [0],
)

__RESULT_BOUNDARY__

超产滞销情形下，模型主动限制难以销售的产量；折价销售则允许超出正常销售量的产量继续贡献 50% 单价收入，
因而采用更多地块—作物组合，七年复算利润提高到 5406.55 万元。这个差异是经济规则变化的结果，而不是同一问题上算法性能的提升。

== 问题二：保守路径方案

Q2 的七年复算利润为 1722.46 万元。年度利润在 207.34—263.29 万元之间，2030 年最高。
模型同时满足地块容量、适配、重茬、豆类覆盖、最小面积与分散度约束。由于参数路径偏保守，该结果更适合作为经营底线方案，而非未来平均收益预测。

== 问题三：随机代理未产生增益

#figure(image("__FIG_PREFIX__figures/figure_02_risk_comparison.pdf", width: 100%), caption: [
Q2 固定方案在两类模拟制度下的风险分布，以及 Q3 相对 Q2 的配对改进。
])

相关样本下 Q2 的平均利润、标准差、5% 分位数和 CVaR 分别为 1775.96、17.94、1746.40 和 1739.51 万元；
独立样本下相应数值为 1776.11、13.06、1754.84 和 1750.12 万元。相关假设增加了左尾波动，但两类制度下均未出现相对零利润的损失样本。
__Q3_BOUNDARY__

= 敏感性与验证

#figure(image("__FIG_PREFIX__figures/figure_03_sensitivity.pdf", width: 100%), caption: [
Q2 固定方案的单因素敏感性。结果为固定方案后评价，不含重新优化。
])

六项正负 5% 扰动的利润绝对变化均不超过 4.68%。亩产下降使利润降低 4.68%，是最敏感因素；需求下降使利润降低 2.07%；
成本正负 5% 对利润的影响约为 0.95%。这些结果说明当前方案在局部参数扰动下具有一定稳定性，但不能外推到更大范围或结构变化。

验证采用三条相互分离的证据链。第一，Python Validator 直接从导出面积重算目标与全部约束，最大违反为 0。
第二，MATLAB Level A 从官方输入和最终决策向量独立重算 17 项目标、残差、面积和敏感性指标，目标最大绝对差为 0，面积和误差不超过 4.2e-11。
第三，MATLAB Level B 独立求解轮作小样例和零收益极限样例，8 项检查全部通过。该证据支持实现正确性和局部模型行为，不等价于完整规模模型的跨语言独立求解。

= 模型评价与改进方向

模型的优点是：分段销售收入、跨年轮作和管理便利性均被显式编码；统一评价器把求解与结果报告分离；
Formal Result、Python Validator 与 MATLAB A+B 构成可复算证据链；Q3 失败时采用预注册降级和 dominance guard，避免将更差候选包装为改进。

局限也很明确。首先，四个主情形的 MIP gap 未关闭，当前证据只能支持可行方案。其次，价格取区间中点、销售量由 2023 产量推导，
会把历史结构带入未来。再次，Q3 相关系数不可由题面识别，完整 SAA 又未在时限内获得整数可行解，因此随机结论只适用于假设分布。
最后，固定方案敏感性没有重新优化，不能反映参数变化后的最优结构调整。

后续可从三方面改进：用滚动时域或 Benders 分解扩大 SAA 可解规模；对相关系数进行区间鲁棒分析；
在保持可复算性的前提下，增加可行贪心基线和更长时限求解，给出更有意义的上下界与竞赛价值比较。

= 结论

本文用分段收入混合整数规划统一求解多期种植安排，并通过独立约束复算、确定性重放和 MATLAB Level A+B 验证结果。
问题一显示销售规则会显著改变可实现利润；问题二给出 1722.46 万元的保守路径可行方案；问题三的受控随机代理未优于 Q2，故最终复用 Q2。
在预注册样本制度内，Q3 的配对均值改进为 0；固定方案的局部敏感性变化不超过 4.68%。
因此，本次计算的主要价值是形成边界清晰、可复算的经营方案，而不是证明随机模型或求解器获得了全局最优改进。

= 附录：证据与复现范围

- Python 负责主求解、正式图表、导出和视觉 QA；图表同时保存 CSV、脚本、SVG、PDF、TIFF、PNG 和 QA 报告。
- MATLAB Level A 完成 17 项独立复算，Level B 完成 2 个小样例共 8 项检查；两者均未完整求解正式规模模型。
- 当前运行分类为 development_integration_benchmark，blind_generalization=false，profile_promotion_eligible=false。
- 正式结果表位于 result1_1_R02.xlsx、result1_2_R02.xlsx、result2_R02.xlsx 和 result3_R02.xlsx。
'''
    return (
        template.replace("__BOUNDARY__", boundary)
        .replace("__BEAN_NOTE__", bean_note)
        .replace("__RESULT_BOUNDARY__", result_boundary)
        .replace("__Q3_BOUNDARY__", q3_boundary)
        .replace("__FIG_PREFIX__", figure_prefix)
    )


def markdown_text(final: bool) -> str:
    note = (
        "> **结论边界：** 全文仅报告时限内约束可行方案；非零 MIP gap 不支持全局最优声明；"
        "Q3 相关结构为预注册假设；MATLAB A+B 不是完整模型独立复现。\n\n"
        if final
        else ""
    )
    return f"""# 面向多期轮作与销售不确定性的农作物种植策略

## 摘要

本文建立分段收入混合整数规划处理 2024—2030 年多地块、多季次种植决策，并用统一评价器、独立 Validator 与 MATLAB Level A+B 复算。
四类情形七年利润分别为 1730.80、5406.55、1722.46 和 1722.46 万元，最大约束违反为 0。Q3 完整 SAA 未完成，受控代理最终复用 Q2，
在相关与独立样本下的配对均值改进均为 0；Q2 固定方案的六项局部敏感性最大绝对变化为 4.68%。

{note}## 核心模型

决策变量为年度、地块、季次和作物对应的种植面积及启用状态。目标函数统一计算正常销量收入、超产折价收入和种植成本，
约束覆盖地块容量、作物适配、水浇地模式、相邻年度重茬、三年豆类覆盖、最小面积与分散度。

## 主要结果

- Q1 超产滞销：1730.80 万元，MIP gap=1.3807。
- Q1 超产折价：5406.55 万元，MIP gap=0.0976；高利润来自销售规则改变，不是算法改进。
- Q2 保守路径：1722.46 万元，MIP gap=1.3996。
- Q3 受控代理：1722.46 万元，MIP gap=1.4338；dominance guard 后复用 Q2。

## 结论

模型给出可复算、约束可行的多期种植方案，但当前证据不支持全局最优或 Q3 优于 Q2 的结论。完整内容与公式见同目录 Typst/PDF 版本。
"""


def compile_manuscript(run_dir: Path, final: bool) -> tuple[Path, Path]:
    if final:
        typ_path = run_dir / "paper/submission_paper_candidate.typ"
        pdf_path = run_dir / "submission_paper_candidate.pdf"
        md_path = run_dir / "paper/submission_paper_candidate.md"
        figure_prefix = ""
    else:
        typ_path = run_dir / "paper/archive/submission_paper_candidate_round1.typ"
        pdf_path = run_dir / "paper/archive/submission_paper_candidate_round1.pdf"
        md_path = run_dir / "paper/archive/submission_paper_candidate_round1.md"
        figure_prefix = "../"
    typ_path.parent.mkdir(parents=True, exist_ok=True)
    typ_path.write_text(manuscript_text(final, figure_prefix), encoding="utf-8")
    md_path.write_text(markdown_text(final), encoding="utf-8")
    subprocess.run(
        ["typst", "compile", str(typ_path), str(pdf_path), "--root", str(run_dir)],
        cwd=run_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if pdf_path.stat().st_size < 10_000:
        raise ValueError("论文 PDF 体积异常，可能编译为空")
    return typ_path, pdf_path


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 2024-C v2.1 Gate 4 论文工件")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--version", choices=("round1", "final"), required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    if read_json(run_dir / "run_manifest.json").get("run_id") != RUN_ID:
        raise ValueError("脚本只允许用于固定的 2024-C v2.1 回放运行")
    admission = read_json(run_dir / "paper_admission_report.json")
    if admission.get("submission_paper_allowed") is not True:
        raise ValueError("Paper Admission 未通过，禁止生成 submission_paper")

    script_copy = run_dir / "paper/scripts/build_2024c_v21_gate4.py"
    script_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), script_copy)
    write_terminology(run_dir)
    final = args.version == "final"
    fragments = [
        build_figure_1(run_dir, script_copy),
        build_figure_2(run_dir, script_copy, final=final),
        build_figure_3(run_dir, script_copy),
    ]
    build_claim_map(run_dir, final=final)
    typ_path, pdf_path = compile_manuscript(run_dir, final=final)
    output = {
        "version": args.version,
        "manuscript": file_ref(run_dir, typ_path),
        "pdf": file_ref(run_dir, pdf_path),
        "figures": [item["figure_id"] for item in fragments],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
