"""从锁定的论文源数据生成黑白 Typst 终稿图，不调用求解器。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image


ROOT = Path(__file__).absolute().parents[2]
SOURCE = ROOT / "figures" / "paper" / "source_data"
OUTPUT = ROOT / "paper" / "figures"

GRAY = {
    "black": "#111111",
    "dark": "#3F3F3F",
    "mid": "#777777",
    "light": "#B0B0B0",
    "pale": "#E2E2E2",
    "white": "#FFFFFF",
}


def configure_style() -> None:
    """统一黑白论文图的字体、线宽和可编辑文本设置。"""
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 7.5,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.8,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_csv(name: str) -> list[dict[str, str]]:
    with (SOURCE / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def save_figure(fig: plt.Figure, stem: str) -> None:
    """导出 SVG、PDF、PNG 和 600 dpi TIFF。"""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    fig.savefig(OUTPUT / f"{stem}.pdf", bbox_inches="tight", facecolor="white")
    fig.savefig(OUTPUT / f"{stem}.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(OUTPUT / f"{stem}.tiff", dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def add_panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(-0.11, 1.04, label, transform=ax.transAxes, fontsize=9, fontweight="bold", va="top")


def workflow_figure() -> None:
    """绘制四问递进关系和独立验证闭环。"""
    fig, ax = plt.subplots(figsize=(7.2, 2.25))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    boxes = [
        (0.02, "问题一", "供应商评价", "四指标排序\n识别 50 家候选"),
        (0.27, "问题二", "最小规模决策", "闭合 25/26 家边界\n采购成本→运输损耗"),
        (0.52, "问题三", "原料结构优化", "C 类→总原料→损耗\n披露分散与拆分"),
        (0.77, "问题四", "产能边界估计", "最大化产品等价到货\n安全库存随产能变化"),
    ]
    fills = [GRAY["pale"], "#D4D4D4", "#C2C2C2", "#B0B0B0"]
    for idx, ((x, step, title, detail), fill) in enumerate(zip(boxes, fills)):
        ax.add_patch(Rectangle((x, 0.43), 0.20, 0.39, facecolor=fill, edgecolor=GRAY["black"], linewidth=1.0))
        ax.text(x + 0.10, 0.75, step, ha="center", va="center", fontsize=7.2)
        ax.text(x + 0.10, 0.64, title, ha="center", va="center", fontsize=9, fontweight="bold")
        ax.text(x + 0.10, 0.51, detail, ha="center", va="center", fontsize=7, linespacing=1.35)
        if idx < len(boxes) - 1:
            ax.annotate("", xy=(x + 0.245, 0.625), xytext=(x + 0.205, 0.625), arrowprops={"arrowstyle": "->", "lw": 1.2, "color": GRAY["black"]})

    ax.add_patch(Rectangle((0.12, 0.10), 0.76, 0.17, facecolor=GRAY["white"], edgecolor=GRAY["black"], linewidth=1.0, hatch="//"))
    ax.text(0.50, 0.185, "独立验证闭环：目标复算  ·  硬约束检查  ·  Excel 回读  ·  故障注入  ·  压力测试", ha="center", va="center", fontsize=8)
    for x in (0.12, 0.37, 0.62, 0.88):
        ax.annotate("", xy=(x, 0.27), xytext=(x, 0.42), arrowprops={"arrowstyle": "<->", "lw": 0.9, "color": GRAY["dark"]})
    fig.tight_layout(pad=0.4)
    save_figure(fig, "fig01_workflow")


def supplier_metrics_figure() -> None:
    rows = read_csv("01_supplier_metric_distributions.csv")
    fields = [
        ("capacity_normalized", "产品等价能力"),
        ("service_normalized", "按单供货概率"),
        ("stability_normalized", "稳定性"),
        ("fulfilment_normalized", "兑现率"),
    ]
    shades = [GRAY["dark"], GRAY["mid"], GRAY["light"], "#929292"]
    hatches = [None, "//", "..", "xx"]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.8), sharex=True)
    for idx, (ax, (field, label), shade, hatch) in enumerate(zip(axes.flat, fields, shades, hatches)):
        values = np.asarray([float(row[field]) for row in rows])
        counts, bins, patches = ax.hist(values, bins=np.linspace(0, 1, 21), color=shade, edgecolor="white", linewidth=0.45)
        if hatch:
            for patch in patches:
                patch.set_hatch(hatch)
        median = float(np.median(values))
        ax.axvline(median, color=GRAY["black"], linestyle="--", linewidth=1.0)
        ax.text(0.98, 0.92, f"中位数 {median:.3f}", transform=ax.transAxes, ha="right", va="top", fontsize=7)
        ax.text(0.02, 0.92, label, transform=ax.transAxes, ha="left", va="top", fontsize=8.2, fontweight="bold")
        ax.set_ylabel("供应商数量（家）")
        ax.set_xlim(-0.02, 1.02)
        add_panel_label(ax, "abcd"[idx])
        ax.set_ylim(0, max(counts) * 1.16)
    for ax in axes[-1, :]:
        ax.set_xlabel("归一化取值")
    fig.subplots_adjust(left=0.09, right=0.985, top=0.96, bottom=0.10, hspace=0.34, wspace=0.26)
    save_figure(fig, "fig02_supplier_metrics")


def top20_figure() -> None:
    rows = read_csv("02_supplier_top20_scores.csv")
    supplier_ids = [row["supplier_id"] for row in rows][::-1]
    scores = np.asarray([float(row["importance_score"]) for row in rows][::-1])
    materials = [row["material_type"] for row in rows][::-1]
    styles = {
        "A": (GRAY["dark"], ""),
        "B": (GRAY["mid"], "//"),
        "C": (GRAY["light"], "xx"),
    }
    fig, ax = plt.subplots(figsize=(7.2, 5.35))
    bars = ax.barh(np.arange(len(rows)), scores, color=[styles[m][0] for m in materials], edgecolor=GRAY["black"], linewidth=0.45)
    for bar, material in zip(bars, materials):
        bar.set_hatch(styles[material][1])
    for y, value in enumerate(scores):
        ax.text(value + 0.008, y, f"{value:.3f}", va="center", fontsize=6.5)
    ax.set_yticks(np.arange(len(rows)), supplier_ids)
    ax.set_xlabel("综合重要性得分")
    ax.set_ylabel("供应商")
    ax.set_xlim(0, 1.02)
    handles = [Rectangle((0, 0), 1, 1, facecolor=styles[m][0], edgecolor=GRAY["black"], hatch=styles[m][1], label=f"{m} 类") for m in ("A", "B", "C")]
    ax.legend(handles=handles, loc="lower right", ncol=3)
    fig.tight_layout(pad=0.65)
    save_figure(fig, "fig03_top20_suppliers")


def rank_sensitivity_figure() -> None:
    rows = read_csv("11_rank_weight_sensitivity.csv")
    labels = [row["case_label"] for row in rows]
    x = np.arange(len(rows))
    top10 = np.asarray([100 * float(row["top10_overlap_rate"]) for row in rows])
    top50 = np.asarray([100 * float(row["top50_overlap_rate"]) for row in rows])
    ranks = np.asarray([int(row["S140_rank"]) for row in rows])
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.9), sharex=True, gridspec_kw={"height_ratios": [1.05, 1]})
    axes[0].plot(x, top10, color=GRAY["black"], marker="o", linewidth=1.4, label="前 10 重合率")
    axes[0].plot(x, top50, color=GRAY["mid"], marker="s", linestyle="--", linewidth=1.4, label="前 50 重合率")
    axes[0].set_ylabel("与基准排序重合率（%）")
    axes[0].set_ylim(65, 102)
    axes[0].legend(loc="lower left", ncol=2)
    add_panel_label(axes[0], "a")

    axes[1].plot(x, ranks, color=GRAY["dark"], marker="D", linewidth=1.4)
    for xi, rank in zip(x, ranks):
        axes[1].text(xi, rank - 1.0 if rank > 8 else rank + 1.6, str(rank), ha="center", fontsize=6.5)
    axes[1].invert_yaxis()
    axes[1].set_ylabel("S140 名次（越小越好）")
    axes[1].set_xticks(x, labels, rotation=27, ha="right")
    add_panel_label(axes[1], "b")
    fig.subplots_adjust(left=0.11, right=0.985, top=0.97, bottom=0.20, hspace=0.18)
    save_figure(fig, "fig04_rank_sensitivity")


def problem2_operations_figure() -> None:
    load_rows = read_csv("05_problem2_transporter_load.csv")
    inv_rows = read_csv("06_problem2_inventory_trajectory.csv")
    transporters = sorted({row["transporter_id"] for row in load_rows}, key=lambda x: int(x[1:]))
    weeks = sorted({int(row["week"]) for row in load_rows})
    load_map = {(row["transporter_id"], int(row["week"])): float(row["load_m3"]) for row in load_rows}
    matrix = np.asarray([[load_map[(t, week)] for week in weeks] for t in transporters])
    inventories = sorted((row for row in inv_rows if row["record_type"] == "inventory"), key=lambda row: int(row["week_or_timepoint"]))
    arrivals = sorted((row for row in inv_rows if row["record_type"] != "inventory"), key=lambda row: int(row["week_or_timepoint"]))

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.2), gridspec_kw={"height_ratios": [1.15, 0.92, 0.92]})
    image = axes[0].imshow(matrix, aspect="auto", cmap="Greys", vmin=0, vmax=6000, interpolation="nearest")
    axes[0].set_yticks(np.arange(len(transporters)), transporters)
    axes[0].set_xticks(np.arange(0, len(weeks), 2), [weeks[i] for i in range(0, len(weeks), 2)])
    axes[0].set_ylabel("转运商")
    axes[0].set_xlabel("周次")
    cbar = fig.colorbar(image, ax=axes[0], fraction=0.028, pad=0.02)
    cbar.set_label("负载（m³/周）")
    add_panel_label(axes[0], "a")

    inv_x = np.asarray([int(row["week_or_timepoint"]) for row in inventories])
    inv_y = np.asarray([float(row["value_product_equivalent_m3"]) for row in inventories])
    inv_ref = np.asarray([float(row["reference_product_equivalent_m3"]) for row in inventories])
    axes[1].plot(inv_x, inv_y, color=GRAY["black"], marker="o", markersize=2.8, linewidth=1.2, label="期末库存")
    axes[1].plot(inv_x, inv_ref, color=GRAY["mid"], linestyle="--", linewidth=1.1, label="两周安全库存")
    axes[1].set_ylabel("产品等价库存（m³）")
    axes[1].set_xlabel("时点（0 为期初）")
    axes[1].set_ylim(min(inv_y) - 300, max(inv_y) + 300)
    axes[1].legend(loc="upper right", ncol=2)
    add_panel_label(axes[1], "b")

    arr_x = np.asarray([int(row["week_or_timepoint"]) for row in arrivals])
    arr_y = np.asarray([float(row["value_product_equivalent_m3"]) for row in arrivals])
    arr_ref = np.asarray([float(row["reference_product_equivalent_m3"]) for row in arrivals])
    axes[2].plot(arr_x, arr_y, color=GRAY["dark"], marker="s", markersize=2.8, linewidth=1.2, label="损耗后到货产品等价量")
    axes[2].plot(arr_x, arr_ref, color=GRAY["mid"], linestyle="--", linewidth=1.1, label="周生产需求")
    axes[2].set_ylabel("产品等价量（m³/周）")
    axes[2].set_xlabel("周次")
    axes[2].set_ylim(min(arr_y) - 160, max(arr_y) + 160)
    axes[2].legend(loc="upper right", ncol=2)
    add_panel_label(axes[2], "c")
    fig.subplots_adjust(left=0.12, right=0.96, top=0.98, bottom=0.08, hspace=0.48)
    save_figure(fig, "fig05_problem2_operations")


def material_mix_figure() -> None:
    rows = read_csv("07_problem3_material_mix.csv")
    problems = ["问题二", "问题三"]
    materials = ["A", "B", "C"]
    values = {(row["problem"], row["material_type"]): float(row["weekly_mean_expected_supply_m3"]) for row in rows}
    styles = {"A": (GRAY["dark"], ""), "B": (GRAY["mid"], "//"), "C": (GRAY["light"], "xx")}
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    bottoms = np.zeros(len(problems))
    for material in materials:
        heights = np.asarray([values[(problem, material)] for problem in problems])
        ax.bar(problems, heights, bottom=bottoms, color=styles[material][0], edgecolor=GRAY["black"], linewidth=0.55, hatch=styles[material][1], label=f"{material} 类")
        bottoms += heights
    for x, total in enumerate(bottoms):
        ax.text(x, total + 220, f"合计 {total:,.1f}", ha="center", fontsize=8)
    ax.set_ylabel("周均期望供货量（m³）")
    ax.set_ylim(0, max(bottoms) * 1.10)
    ax.legend(loc="lower left", ncol=3)
    fig.tight_layout(pad=0.65)
    save_figure(fig, "fig06_material_mix")


def capacity_figure() -> None:
    rows = read_csv("09_problem4_capacity_comparison.csv")
    values = [float(row["weekly_capacity_m3"]) for row in rows]
    increase = 100 * float(rows[1]["increase_ratio_vs_baseline"])
    labels = ["基准周需求", "模型预测最大周产能"]
    fig, ax = plt.subplots(figsize=(6.3, 4.15))
    bars = ax.bar(labels, values, color=[GRAY["mid"], GRAY["light"]], edgecolor=GRAY["black"], linewidth=0.7)
    bars[0].set_hatch("//")
    bars[1].set_hatch("xx")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 420, f"{value:,.3f}", ha="center", fontsize=8)
    ax.annotate(f"增加 {increase:.4f}%", xy=(1, values[1] * 0.91), xytext=(0, values[0] * 1.08), ha="center", arrowprops={"arrowstyle": "->", "lw": 1.0, "color": GRAY["black"]}, fontsize=8)
    ax.set_ylabel("周产能（m³/周）")
    ax.set_ylim(0, values[1] * 1.15)
    fig.tight_layout(pad=0.7)
    save_figure(fig, "fig07_capacity")


def stress_figure() -> None:
    rows = read_csv("10_sensitivity_and_stress_tests.csv")
    feasible = [row for row in rows if row["feasibility_status"] == "feasible"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.65), gridspec_kw={"width_ratios": [1, 1.45]})
    x1 = np.arange(len(feasible))
    counts = np.asarray([int(row["selected_supplier_count"]) for row in feasible])
    bars = axes[0].bar(x1, counts, color=GRAY["mid"], edgecolor=GRAY["black"], linewidth=0.6, hatch="//")
    for bar, value in zip(bars, counts):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.5, str(value), ha="center", fontsize=7)
    axes[0].set_xticks(x1, [row["scenario_label"] for row in feasible], rotation=25, ha="right")
    axes[0].set_ylabel("供应商数量（家）")
    axes[0].set_ylim(0, max(counts) + 4)
    add_panel_label(axes[0], "a")

    status_style = {
        "feasible": (GRAY["light"], "//", "可行"),
        "feasible_not_proven_optimal": (GRAY["mid"], "..", "可行\n未证最优"),
        "infeasible": (GRAY["dark"], "xx", "不可行"),
        "globally_infeasible": (GRAY["dark"], "xx", "全局不可行"),
        "unknown_time_limit": (GRAY["mid"], "..", "限时未知"),
        "no_feasible_solution_found_within_limit": (GRAY["mid"], "..", "限时未找到"),
        "unable_to_determine": (GRAY["mid"], "..", "无法判定"),
    }
    for idx, row in enumerate(rows):
        fill, hatch, label = status_style[row["feasibility_status"]]
        bar = axes[1].bar(idx, 1, color=fill, edgecolor=GRAY["black"], linewidth=0.6, hatch=hatch)[0]
        text_color = "white" if row["feasibility_status"] in {"infeasible", "globally_infeasible"} else "black"
        axes[1].text(bar.get_x() + bar.get_width() / 2, 0.5, label, ha="center", va="center", color=text_color, fontsize=6.5, fontweight="bold")
    axes[1].set_xticks(np.arange(len(rows)), [row["scenario_label"] for row in rows], rotation=28, ha="right")
    axes[1].set_yticks([])
    axes[1].set_ylim(0, 1)
    axes[1].spines["left"].set_visible(False)
    axes[1].spines["bottom"].set_visible(False)
    add_panel_label(axes[1], "b")
    fig.subplots_adjust(left=0.09, right=0.985, top=0.96, bottom=0.26, wspace=0.24)
    save_figure(fig, "fig08_stress")


def write_qa() -> None:
    """记录导出完整性、哈希和灰度检查。"""
    report: dict[str, object] = {"backend": "python", "figure_count": 8, "figures": {}, "passed": True}
    for stem in [
        "fig01_workflow",
        "fig02_supplier_metrics",
        "fig03_top20_suppliers",
        "fig04_rank_sensitivity",
        "fig05_problem2_operations",
        "fig06_material_mix",
        "fig07_capacity",
        "fig08_stress",
    ]:
        paths = {suffix: OUTPUT / f"{stem}.{suffix}" for suffix in ("svg", "pdf", "png", "tiff")}
        with Image.open(paths["png"]) as image:
            rgb = np.asarray(image.convert("RGB"))
            grayscale = bool(np.array_equal(rgb[..., 0], rgb[..., 1]) and np.array_equal(rgb[..., 1], rgb[..., 2]))
            pixel_size = list(image.size)
        svg_text = paths["svg"].read_text(encoding="utf-8")
        item = {
            "all_formats_present": all(path.exists() and path.stat().st_size > 0 for path in paths.values()),
            "png_grayscale": grayscale,
            "svg_editable_text": "<text" in svg_text,
            "png_pixel_size": pixel_size,
            "sha256": {suffix: hashlib.sha256(path.read_bytes()).hexdigest() for suffix, path in paths.items()},
        }
        item["passed"] = bool(item["all_formats_present"] and item["png_grayscale"] and item["svg_editable_text"])
        report["figures"][stem] = item
        report["passed"] = bool(report["passed"] and item["passed"])
    (OUTPUT / "figure_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    configure_style()
    workflow_figure()
    supplier_metrics_figure()
    top20_figure()
    rank_sensitivity_figure()
    problem2_operations_figure()
    material_mix_figure()
    capacity_figure()
    stress_figure()
    write_qa()


if __name__ == "__main__":
    main()
