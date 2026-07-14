"""从既有结果工件生成论文图表，不调用求解器、不改变任何目标值。"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.ticker import StrMethodFormatter
from PIL import Image


# 保留启动路径，避免 Windows 子进程在中文目录上错误解析联接目标。
ROOT = Path(__file__).absolute().parents[2]
CODE = ROOT / "code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from common.common import DEMAND_BASE, load_official_data  # noqa: E402


FIGURE_DIR = ROOT / "figures" / "paper"
SOURCE_DATA_DIR = FIGURE_DIR / "source_data"
RESULTS = ROOT / "results"
COLORS = {
    "blue": "#4E6E8E",
    "sky": "#8FB6C9",
    "green": "#6D9F86",
    "orange": "#D5A45B",
    "vermillion": "#B86755",
    "purple": "#9A7FA2",
    "yellow": "#D7C56C",
    "gray": "#747474",
    "light_gray": "#D6D8DA",
    "dark": "#30343B",
}
MATERIAL_COLORS = {"A": COLORS["blue"], "B": COLORS["orange"], "C": COLORS["green"]}

FIGURE_CONTRACTS = {
    "01_supplier_metric_distributions": {
        "paper_figure": 1,
        "conclusion": "供应商能力高度集中，可靠性指标的离散说明仅按规模排序不足以评价保障作用。",
        "archetype": "quantitative grid",
        "evidence": "四项评价指标在 402 家供应商上的归一化分布及其中位数。",
        "reviewer_risk": "归一化会隐藏原始单位，因此源数据同时保留原始值和归一化值。",
    },
    "03_material_capacity_distribution": {
        "paper_figure": 2,
        "conclusion": "三类原料的供应商数量相近，但产品等价常规期望供货上限分布存在差异。",
        "archetype": "quantitative grid",
        "evidence": "类别计数与按类别分组的产品等价能力分布。",
        "reviewer_risk": "箱线图隐藏极端点，源数据保留全部 402 家供应商。",
    },
    "02_supplier_top20_scores": {
        "paper_figure": 3,
        "conclusion": "在给定业务权重下，前 20 家供应商形成明确但非绝对客观的候选排序。",
        "archetype": "quantitative grid",
        "evidence": "前 20 家综合得分、排名和原料类别。",
        "reviewer_risk": "权重具有主观业务属性，必须与图 4 的敏感性结果联合解释。",
    },
    "11_rank_weight_sensitivity": {
        "paper_figure": 4,
        "conclusion": "小幅单项权重扰动下整体排序稳定，但等权会使 S140 从第 3 降至第 53。",
        "archetype": "quantitative grid",
        "evidence": "前 10 重合数、前 50 重合率、Spearman 相关系数及 S140 名次。",
        "reviewer_risk": "不能把局部稳定性解释为权重客观或排序绝对稳健。",
    },
    "04_problem2_weekly_orders": {
        "paper_figure": 5,
        "conclusion": "平稳参数使问题二的周订购结构在 24 周保持一致。",
        "archetype": "quantitative grid",
        "evidence": "A/B/C 类及总订购量的逐周轨迹。",
        "reviewer_risk": "恒定轨迹来自平稳假设，不代表真实未来不存在周波动。",
    },
    "05_problem2_transporter_load": {
        "paper_figure": 6,
        "conclusion": "低损耗转运商 T3、T6 饱和，T2 接近饱和，构成问题二的运输瓶颈。",
        "archetype": "quantitative grid",
        "evidence": "8 家转运商 24 周负载及 6000 m3/周容量上限。",
        "reviewer_risk": "热图必须使用固定 0-6000 标尺，避免跨转运商比较失真。",
    },
    "06_problem2_inventory_trajectory": {
        "paper_figure": 7,
        "conclusion": "损耗后到货恰好满足周需求，库存始终贴合两周安全下界。",
        "archetype": "quantitative grid",
        "evidence": "库存轨迹与逐周产品等价到货量。",
        "reviewer_risk": "库存贴边是模型目标和无仓储奖励共同造成，不能泛化为现实最优库存。",
    },
    "07_problem3_material_mix": {
        "paper_figure": 8,
        "conclusion": "问题三的词典序目标提高 A 类、压低 C 类并减少总原料用量。",
        "archetype": "quantitative grid",
        "evidence": "问题二与问题三的 A/B/C 周均期望供货量对比。",
        "reviewer_risk": "结构改善不等于运营更易执行，需结合供应商分散性解释。",
    },
    "08_problem3_transport_splitting": {
        "paper_figure": 9,
        "conclusion": "问题三拆分发生频率低，但涉及的运输量占比不可忽略。",
        "archetype": "quantitative grid",
        "evidence": "拆分供应商-周计数和拆分运输量构成。",
        "reviewer_risk": "计数占比与体积占比口径不同，图注必须分别说明分母。",
    },
    "09_problem4_capacity_comparison": {
        "paper_figure": 10,
        "conclusion": "历史能力与平均损耗假设下的模型预测周产能比基准高 18.2125%。",
        "archetype": "quantitative grid",
        "evidence": "基准周产能与模型预测最大周产能。",
        "reviewer_risk": "必须标为模型预测值，不能写成保证产能。",
    },
    "10_sensitivity_and_stress_tests": {
        "paper_figure": 11,
        "conclusion": "基准方案对需求增长和关键供应商全期中断缺少冗余，限时未知状态不能写成不可行。",
        "archetype": "quantitative grid",
        "evidence": "可行情景的供应商数量和全部压力情景的求解状态。",
        "reviewer_risk": "unknown_time_limit 与 infeasible 必须使用不同编码和文字。",
    },
}


def read_json(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def configure_style() -> None:
    """统一论文图形的字体、线宽和低饱和色彩层级。"""
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "Arial", "SimHei", "DengXian", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.8,
            "axes.grid": False,
            "legend.frameon": False,
            "figure.dpi": 120,
            "savefig.dpi": 600,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def save_figure(fig: plt.Figure, stem: str) -> None:
    """导出可编辑矢量图、预览图和 600 dpi TIFF。"""
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    fig.savefig(FIGURE_DIR / f"{stem}.pdf", bbox_inches="tight", facecolor="white")
    fig.savefig(FIGURE_DIR / f"{stem}.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(FIGURE_DIR / f"{stem}.tiff", dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_source_data(stem: str, rows: list[dict]) -> None:
    """将每幅图的绘图数据保存为独立 CSV，便于逐点复核。"""
    if not rows:
        raise ValueError(f"{stem} 没有可导出的源数据")
    SOURCE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with (SOURCE_DATA_DIR / f"{stem}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def add_panel_labels(axes, labels: str = "abcdefghijklmnopqrstuvwxyz") -> None:
    """为多面板图添加统一的小写粗体面板标签。"""
    for label, ax in zip(labels, np.asarray(axes, dtype=object).flat):
        ax.text(-0.12, 1.06, label, transform=ax.transAxes, fontsize=9, fontweight="bold", va="top")


def write_figure_contracts() -> None:
    """输出逐图结论、证据链和审稿风险，作为图形审计记录。"""
    lines = ["# 论文图形契约", "", "全部图形由既有结果数据生成，不调用求解器。", ""]
    for stem, item in sorted(FIGURE_CONTRACTS.items(), key=lambda pair: pair[1]["paper_figure"]):
        lines.extend(
            [
                f"## 图 {item['paper_figure']} | {stem}",
                "",
                f"- 核心结论：{item['conclusion']}",
                f"- 图形类型：{item['archetype']}",
                f"- 证据链：{item['evidence']}",
                f"- 审稿风险：{item['reviewer_risk']}",
                f"- 源数据：source_data/{stem}.csv",
                "",
            ]
        )
    (FIGURE_DIR / "figure_contracts.md").write_text("\n".join(lines), encoding="utf-8")


def write_qa_report() -> dict:
    """检查导出格式、源数据、可编辑文本与栅格尺寸。"""
    required_formats = ("svg", "pdf", "png", "tiff")
    report = {"backend": "python", "paper_figure_count": len(FIGURE_CONTRACTS), "figures": {}, "passed": True}
    for stem, contract in FIGURE_CONTRACTS.items():
        files = {suffix: FIGURE_DIR / f"{stem}.{suffix}" for suffix in required_formats}
        source_path = SOURCE_DATA_DIR / f"{stem}.csv"
        png_size = None
        tiff_dpi = None
        if files["png"].exists():
            with Image.open(files["png"]) as image:
                png_size = list(image.size)
        if files["tiff"].exists():
            with Image.open(files["tiff"]) as image:
                dpi = image.info.get("dpi")
                tiff_dpi = [float(value) for value in dpi] if dpi else None
        svg_editable_text = files["svg"].exists() and "<text" in files["svg"].read_text(encoding="utf-8")
        source_rows = 0
        if source_path.exists():
            with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
                source_rows = max(sum(1 for _ in handle) - 1, 0)
        checks = {
            "all_formats_present": all(path.exists() and path.stat().st_size > 0 for path in files.values()),
            "svg_editable_text": svg_editable_text,
            "source_data_present": source_rows > 0,
            "png_pixel_size": png_size,
            "tiff_dpi": tiff_dpi,
        }
        passed = checks["all_formats_present"] and checks["svg_editable_text"] and checks["source_data_present"]
        report["figures"][stem] = {
            "paper_figure": contract["paper_figure"],
            "passed": passed,
            "source_rows": source_rows,
            "checks": checks,
        }
        report["passed"] = report["passed"] and passed
    (FIGURE_DIR / "figure_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def normalise(values: np.ndarray) -> np.ndarray:
    low, high = float(np.min(values)), float(np.max(values))
    if high - low <= 1e-12:
        return np.zeros_like(values)
    return (values - low) / (high - low)


def supplier_metric_distributions(data: dict) -> None:
    metrics = data["supplier_metrics"]
    capacity = np.array([m["product_equivalent_capacity_before_loss"] for m in metrics])
    service = np.array([m["service_probability"] for m in metrics])
    stability = np.array(
        [1.0 / (1.0 + m["supply_cv_positive_weeks"]) if m["supply_cv_positive_weeks"] is not None else 0.0 for m in metrics]
    )
    fulfilment = np.array([min(m["weighted_fulfilment_ratio"], 1.0) for m in metrics])
    normalized = {
        "capacity": normalise(capacity),
        "service": normalise(service),
        "stability": normalise(stability),
        "fulfilment": normalise(fulfilment),
    }
    series = [
        (normalized["capacity"], "产能指标（归一化）", COLORS["blue"]),
        (normalized["service"], "按单供货概率（归一化）", COLORS["orange"]),
        (normalized["stability"], "稳定性指标（归一化）", COLORS["green"]),
        (normalized["fulfilment"], "兑现率指标（归一化）", COLORS["purple"]),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(8.0, 5.4), constrained_layout=True)
    for ax, (values, title, color) in zip(axes.flat, series):
        ax.hist(values, bins=20, color=color, alpha=0.88, edgecolor="white", linewidth=0.5)
        ax.axvline(np.median(values), color=COLORS["dark"], linestyle="--", linewidth=1.0, label=f"中位数 {np.median(values):.3f}")
        ax.set_title(title)
        ax.set_xlabel("归一化取值")
        ax.set_ylabel("供应商数量（家）")
        ax.set_xlim(-0.02, 1.02)
        ax.legend()
    add_panel_labels(axes)
    fig.suptitle("402 家供应商四项评价指标分布", fontsize=10, fontweight="bold")
    write_source_data(
        "01_supplier_metric_distributions",
        [
            {
                "supplier_id": supplier_id,
                "material_type": material_type,
                "capacity_product_equivalent_m3_per_week": capacity[index],
                "service_probability": service[index],
                "stability_index": stability[index],
                "fulfilment_ratio_capped": fulfilment[index],
                "capacity_normalized": normalized["capacity"][index],
                "service_normalized": normalized["service"][index],
                "stability_normalized": normalized["stability"][index],
                "fulfilment_normalized": normalized["fulfilment"][index],
            }
            for index, (supplier_id, material_type) in enumerate(zip(data["supplier_ids"], data["material_types"]))
        ],
    )
    save_figure(fig, "01_supplier_metric_distributions")


def supplier_top20_scores(supplier_analysis: dict) -> None:
    ranked_top20 = supplier_analysis["top50"][:20]
    top20 = ranked_top20[::-1]
    labels = [item["supplier_id"] for item in top20]
    scores = [item["importance_score"] for item in top20]
    colors = [MATERIAL_COLORS[item["material_type"]] for item in top20]
    fig, ax = plt.subplots(figsize=(7.2, 5.4), constrained_layout=True)
    bars = ax.barh(labels, scores, color=colors, edgecolor="white", linewidth=0.4)
    ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=7)
    ax.set_xlabel("综合重要性得分")
    ax.set_ylabel("供应商")
    ax.set_xlim(0, max(scores) * 1.14)
    ax.set_title("供应商综合重要性得分前 20 名")
    handles = [mpl.patches.Patch(color=MATERIAL_COLORS[k], label=f"{k} 类") for k in "ABC"]
    ax.legend(handles=handles, loc="lower right")
    write_source_data(
        "02_supplier_top20_scores",
        [
            {
                "rank": rank,
                "supplier_id": item["supplier_id"],
                "material_type": item["material_type"],
                "importance_score": item["importance_score"],
            }
            for rank, item in enumerate(ranked_top20, start=1)
        ],
    )
    save_figure(fig, "02_supplier_top20_scores")


def material_capacity_distribution(data: dict) -> None:
    material = np.asarray(data["material_types"])
    capacity = np.asarray(
        [m["product_equivalent_capacity_before_loss"] for m in data["supplier_metrics"]], dtype=float
    )
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.6), constrained_layout=True)
    counts = [int(np.sum(material == k)) for k in "ABC"]
    axes[0].bar(list("ABC"), counts, color=[MATERIAL_COLORS[k] for k in "ABC"])
    axes[0].set_title("供应商类别构成")
    axes[0].set_xlabel("原料类别")
    axes[0].set_ylabel("供应商数量（家）")
    for index, value in enumerate(counts):
        axes[0].text(index, value + 3, str(value), ha="center", va="bottom")
    box_data = [capacity[material == k] for k in "ABC"]
    box = axes[1].boxplot(
        box_data,
        tick_labels=list("ABC"),
        patch_artist=True,
        showfliers=True,
        flierprops={"marker": "o", "markersize": 2.2, "markerfacecolor": COLORS["gray"], "markeredgewidth": 0, "alpha": 0.38},
    )
    for patch, key in zip(box["boxes"], "ABC"):
        patch.set_facecolor(MATERIAL_COLORS[key])
        patch.set_alpha(0.78)
    axes[1].set_title("常规期望供货上限分布（对称对数轴）")
    axes[1].set_xlabel("原料类别")
    axes[1].set_ylabel("产品等价产能（m³/周）")
    axes[1].set_yscale("symlog", linthresh=1.0)
    axes[1].yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    add_panel_labels(axes)
    write_source_data(
        "03_material_capacity_distribution",
        [
            {
                "supplier_id": supplier_id,
                "material_type": material_type,
                "capacity_product_equivalent_m3_per_week": capacity[index],
            }
            for index, (supplier_id, material_type) in enumerate(zip(data["supplier_ids"], material))
        ],
    )
    save_figure(fig, "03_material_capacity_distribution")


def weekly_by_material(matrix: np.ndarray, material_types: np.ndarray) -> dict[str, np.ndarray]:
    return {key: matrix[material_types == key].sum(axis=0) for key in "ABC"}


def problem2_weekly_orders(raw: dict) -> None:
    p2 = raw["problems"]["2"]
    orders = np.asarray(p2["orders_raw_m3"], dtype=float)
    material = np.asarray(p2["material_types"])
    weekly = weekly_by_material(orders, material)
    weeks = np.arange(1, orders.shape[1] + 1)
    fig, ax = plt.subplots(figsize=(8.2, 3.8), constrained_layout=True)
    ax.stackplot(
        weeks,
        weekly["A"],
        weekly["B"],
        weekly["C"],
        labels=["A 类", "B 类", "C 类"],
        colors=[MATERIAL_COLORS[k] for k in "ABC"],
        alpha=0.86,
    )
    total = orders.sum(axis=0)
    ax.plot(weeks, total, color=COLORS["dark"], linewidth=1.2, label="总订购量")
    ax.set_title("问题二未来 24 周原料订购量")
    ax.set_xlabel("周次")
    ax.set_ylabel("订购量（m³）")
    ax.set_xticks(np.arange(1, 25, 2))
    ax.margins(y=0.08)
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.03))
    write_source_data(
        "04_problem2_weekly_orders",
        [
            {
                "week": int(week),
                "material_A_order_m3": weekly["A"][index],
                "material_B_order_m3": weekly["B"][index],
                "material_C_order_m3": weekly["C"][index],
                "total_order_m3": total[index],
            }
            for index, week in enumerate(weeks)
        ],
    )
    save_figure(fig, "04_problem2_weekly_orders")


def problem2_transporter_load(raw: dict) -> None:
    p2 = raw["problems"]["2"]
    shipments = np.asarray(p2["shipments_raw_m3"], dtype=float)
    loads = shipments.sum(axis=0).T
    fig, ax = plt.subplots(figsize=(8.4, 3.5), constrained_layout=True)
    image = ax.imshow(loads, aspect="auto", cmap="Blues", vmin=0, vmax=6000)
    ax.set_title("问题二各转运商周负载")
    ax.set_xlabel("周次")
    ax.set_ylabel("转运商")
    ax.set_xticks(np.arange(0, 24, 2), labels=np.arange(1, 25, 2))
    ax.set_yticks(np.arange(len(p2["transporter_ids"])), labels=p2["transporter_ids"])
    colorbar = fig.colorbar(image, ax=ax, pad=0.02)
    colorbar.set_label("负载（m³/周）")
    write_source_data(
        "05_problem2_transporter_load",
        [
            {
                "transporter_id": transporter_id,
                "week": week + 1,
                "load_m3": loads[transporter_index, week],
                "capacity_m3": 6000.0,
                "load_ratio": loads[transporter_index, week] / 6000.0,
            }
            for transporter_index, transporter_id in enumerate(p2["transporter_ids"])
            for week in range(loads.shape[1])
        ],
    )
    save_figure(fig, "05_problem2_transporter_load")


def problem2_inventory(raw: dict) -> None:
    p2 = raw["problems"]["2"]
    inventory = np.asarray(p2["inventory_product_equivalent_m3"], dtype=float)
    arrival = np.asarray(p2["arrivals_product_equivalent_m3"], dtype=float)
    demand = float(p2["demand_product_m3_per_week"])
    weeks_inventory = np.arange(0, inventory.size)
    weeks = np.arange(1, arrival.size + 1)
    fig, axes = plt.subplots(2, 1, figsize=(8.2, 5.0), sharex=False, constrained_layout=True)
    axes[0].plot(weeks_inventory, inventory, color=COLORS["blue"], marker="o", markersize=3, label="期末库存")
    axes[0].axhline(2 * demand, color=COLORS["vermillion"], linestyle="--", label="两周安全库存")
    axes[0].set_title("问题二库存轨迹")
    axes[0].set_xlabel("时点（0 为期初）")
    axes[0].set_ylabel("产品等价库存（m³）")
    axes[0].legend()
    axes[1].plot(weeks, arrival, color=COLORS["green"], marker="s", markersize=3, label="损耗后到货产品等价量")
    axes[1].axhline(demand, color=COLORS["dark"], linestyle="--", label="周生产需求")
    axes[1].set_xlabel("周次")
    axes[1].set_ylabel("产品等价量（m³/周）")
    axes[1].set_xticks(np.arange(1, 25, 2))
    axes[1].legend()
    add_panel_labels(axes)
    rows = [
        {
            "record_type": "inventory",
            "week_or_timepoint": int(index),
            "value_product_equivalent_m3": value,
            "reference_product_equivalent_m3": 2 * demand,
        }
        for index, value in enumerate(inventory)
    ]
    rows.extend(
        {
            "record_type": "arrival",
            "week_or_timepoint": int(index + 1),
            "value_product_equivalent_m3": value,
            "reference_product_equivalent_m3": demand,
        }
        for index, value in enumerate(arrival)
    )
    write_source_data("06_problem2_inventory_trajectory", rows)
    save_figure(fig, "06_problem2_inventory_trajectory")


def problem3_material_mix(raw: dict) -> None:
    material = np.asarray(raw["problems"]["2"]["material_types"])
    values = []
    for part in ("2", "3"):
        expected = np.asarray(raw["problems"][part]["expected_supply_raw_m3"], dtype=float)
        values.append([expected[material == key].sum() / 24.0 for key in "ABC"])
    values_array = np.asarray(values)
    fig, ax = plt.subplots(figsize=(6.8, 4.0), constrained_layout=True)
    x = np.arange(2)
    bottom = np.zeros(2)
    for index, key in enumerate("ABC"):
        ax.bar(x, values_array[:, index], bottom=bottom, color=MATERIAL_COLORS[key], label=f"{key} 类")
        bottom += values_array[:, index]
    ax.set_xticks(x, labels=["问题二", "问题三"])
    ax.set_ylabel("周均期望供货量（m³）")
    ax.set_title("问题三原料结构与问题二对比")
    ax.legend(ncol=3)
    for index, total in enumerate(bottom):
        ax.text(index, total + 160, f"合计 {total:,.1f}", ha="center", va="bottom", fontsize=8)
    write_source_data(
        "07_problem3_material_mix",
        [
            {
                "problem": problem,
                "material_type": material_type,
                "weekly_mean_expected_supply_m3": values_array[problem_index, material_index],
            }
            for problem_index, problem in enumerate(("问题二", "问题三"))
            for material_index, material_type in enumerate("ABC")
        ],
    )
    save_figure(fig, "07_problem3_material_mix")


def problem3_transport_splitting(split: dict) -> None:
    p3 = split["by_problem"]["3"]
    active = p3["active_supplier_week_count"]
    split_count = p3["split_supplier_week_count"]
    volume_total = p3["total_transport_volume_raw_m3"]
    split_volume = p3["volume_in_split_supplier_weeks_raw_m3"]
    secondary = p3["secondary_carrier_volume_raw_m3"]
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.8), constrained_layout=True)
    axes[0].bar(["未拆分", "发生拆分"], [active - split_count, split_count], color=[COLORS["light_gray"], COLORS["vermillion"]])
    axes[0].set_title("供应商-周拆分次数")
    axes[0].set_ylabel("供应商-周数量")
    axes[0].text(1, split_count + active * 0.015, f"{split_count}\n({split_count/active:.2%})", ha="center")
    volume_values = [volume_total - split_volume, split_volume - secondary, secondary]
    axes[1].bar(
        ["非拆分周运输", "拆分周主承运", "拆分周次承运"],
        volume_values,
        color=[COLORS["light_gray"], COLORS["sky"], COLORS["orange"]],
    )
    axes[1].set_title("拆分运输量构成")
    axes[1].set_ylabel("24 周运输量（m³）")
    axes[1].tick_params(axis="x", rotation=12)
    for index, value in enumerate(volume_values):
        axes[1].text(index, value + volume_total * 0.015, f"{value/volume_total:.1%}", ha="center", fontsize=8)
    add_panel_labels(axes)
    write_source_data(
        "08_problem3_transport_splitting",
        [
            {
                "metric_group": "supplier_week_count",
                "category": "unsplit",
                "value": active - split_count,
                "denominator": active,
                "share": (active - split_count) / active,
            },
            {
                "metric_group": "supplier_week_count",
                "category": "split",
                "value": split_count,
                "denominator": active,
                "share": split_count / active,
            },
            {
                "metric_group": "transport_volume_m3",
                "category": "non_split_supplier_weeks",
                "value": volume_total - split_volume,
                "denominator": volume_total,
                "share": (volume_total - split_volume) / volume_total,
            },
            {
                "metric_group": "transport_volume_m3",
                "category": "split_week_primary_carrier",
                "value": split_volume - secondary,
                "denominator": volume_total,
                "share": (split_volume - secondary) / volume_total,
            },
            {
                "metric_group": "transport_volume_m3",
                "category": "split_week_secondary_carrier",
                "value": secondary,
                "denominator": volume_total,
                "share": secondary / volume_total,
            },
        ],
    )
    save_figure(fig, "08_problem3_transport_splitting")


def problem4_capacity(raw: dict) -> None:
    maximum = float(raw["problems"]["4"]["maximum_weekly_production_m3"])
    fig, ax = plt.subplots(figsize=(5.8, 4.0), constrained_layout=True)
    bars = ax.bar(["基准产能", "模型预测最大产能"], [DEMAND_BASE, maximum], color=[COLORS["gray"], COLORS["green"]], width=0.62)
    ax.set_ylabel("周产能（m³/周）")
    ax.set_title("基准周需求与模型预测最大产能")
    ax.bar_label(bars, labels=[f"{DEMAND_BASE:,.0f}", f"{maximum:,.3f}"], padding=4)
    ax.text(0.5, maximum * 0.92, f"提升 {(maximum / DEMAND_BASE - 1):.4%}", ha="center", color=COLORS["vermillion"], fontsize=10)
    ax.set_ylim(0, maximum * 1.14)
    write_source_data(
        "09_problem4_capacity_comparison",
        [
            {"scenario": "baseline", "weekly_capacity_m3": DEMAND_BASE, "increase_ratio_vs_baseline": 0.0},
            {
                "scenario": "model_predicted_maximum",
                "weekly_capacity_m3": maximum,
                "increase_ratio_vs_baseline": maximum / DEMAND_BASE - 1,
            },
        ],
    )
    save_figure(fig, "09_problem4_capacity_comparison")


def sensitivity_stress_tests(sensitivity: dict) -> None:
    scenarios = sensitivity["scenarios"]
    label_map = {
        "demand_minus_10pct": "需求 -10%",
        "demand_base": "基准",
        "demand_plus_10pct": "需求 +10%",
        "loss_low_80pct": "损耗 ×0.8",
        "loss_high_120pct": "损耗 ×1.2",
        "key_supplier_capacity_minus_10pct": "关键商能力 -10%",
        "key_supplier_outage": "关键商中断",
    }
    feasible = [item for item in scenarios if item.get("feasible") is True]
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.2), constrained_layout=True)
    names = [label_map[item["scenario"]] for item in feasible]
    selected = [item["selected_supplier_count"] for item in feasible]
    bars = axes[0].bar(names, selected, color=COLORS["blue"], width=0.68)
    axes[0].bar_label(bars, padding=3)
    axes[0].set_title("可行情景的供应商数量")
    axes[0].set_ylabel("供应商数量（家）")
    axes[0].tick_params(axis="x", rotation=20)
    status_codes = []
    status_text = []
    for item in scenarios:
        if item.get("feasible") is True:
            status_codes.append(0)
            status_text.append("可行")
        elif item.get("feasibility_status") == "unknown_time_limit":
            status_codes.append(1)
            status_text.append("unknown")
        else:
            status_codes.append(2)
            status_text.append("不可行")
    status_matrix = np.asarray(status_codes, dtype=float)[None, :]
    cmap = ListedColormap([COLORS["green"], COLORS["orange"], COLORS["vermillion"]])
    axes[1].imshow(status_matrix, aspect="auto", cmap=cmap, vmin=-0.5, vmax=2.5)
    axes[1].set_xticks(np.arange(len(scenarios)), labels=[label_map[item["scenario"]] for item in scenarios], rotation=28, ha="right")
    axes[1].set_yticks([])
    axes[1].set_title("压力测试求解状态")
    for index, text in enumerate(status_text):
        axes[1].text(index, 0, text, ha="center", va="center", color="white" if status_codes[index] != 1 else "black", fontsize=8, fontweight="bold")
    axes[1].grid(False)
    add_panel_labels(axes)
    write_source_data(
        "10_sensitivity_and_stress_tests",
        [
            {
                "scenario": item["scenario"],
                "scenario_label": label_map[item["scenario"]],
                "feasibility_status": "feasible" if item.get("feasible") is True else item.get("feasibility_status", "unknown"),
                "selected_supplier_count": item.get("selected_supplier_count", ""),
                "weekly_purchase_cost_relative": item.get("objective", {}).get("purchase_cost_relative", "") / 24.0
                if item.get("objective")
                else "",
            }
            for item in scenarios
        ],
    )
    save_figure(fig, "10_sensitivity_and_stress_tests")


def rank_weight_sensitivity(rank_sensitivity: dict) -> None:
    cases = rank_sensitivity["cases"]
    names = list(cases.keys())
    display = {
        "current": "当前权重",
        "equal": "等权",
        "capacity_minus_10pct": "产能 -10%",
        "capacity_plus_10pct": "产能 +10%",
        "service_minus_10pct": "服务 -10%",
        "service_plus_10pct": "服务 +10%",
        "stability_minus_10pct": "稳定 -10%",
        "stability_plus_10pct": "稳定 +10%",
        "fulfilment_minus_10pct": "兑现 -10%",
        "fulfilment_plus_10pct": "兑现 +10%",
    }
    top10 = [cases[name]["top10_overlap_count_with_current"] * 10 for name in names]
    top50 = [cases[name]["top50_overlap_rate_with_current"] * 100 for name in names]
    spearman = [cases[name]["spearman_rank_correlation_with_current"] for name in names]
    s140 = [rank_sensitivity["focus_suppliers"]["S140"]["ranks_by_case"][name] for name in names]
    x = np.arange(len(names))
    fig, axes = plt.subplots(2, 1, figsize=(9.0, 5.8), sharex=True, constrained_layout=True)
    axes[0].plot(x, top10, marker="o", color=COLORS["blue"], label="前 10 重合率")
    axes[0].plot(x, top50, marker="s", color=COLORS["green"], label="前 50 重合率")
    axes[0].set_ylabel("与当前排序的重合率（%）")
    axes[0].set_ylim(65, 102)
    axes[0].set_title("供应商排序对权重设置的敏感性")
    axes[0].legend(ncol=2)
    axes[1].plot(x, s140, marker="o", color=COLORS["vermillion"])
    axes[1].invert_yaxis()
    axes[1].set_ylabel("S140 名次（越小越好）")
    axes[1].set_xticks(x, labels=[display[name] for name in names], rotation=30, ha="right")
    for index, value in enumerate(s140):
        axes[1].text(index, value, str(value), ha="center", va="bottom", fontsize=7)
    add_panel_labels(axes)
    write_source_data(
        "11_rank_weight_sensitivity",
        [
            {
                "case": name,
                "case_label": display[name],
                "top10_overlap_count": cases[name]["top10_overlap_count_with_current"],
                "top10_overlap_rate": cases[name]["top10_overlap_count_with_current"] / 10.0,
                "top50_overlap_rate": cases[name]["top50_overlap_rate_with_current"],
                "spearman_rank_correlation": spearman[index],
                "S140_rank": s140[index],
            }
            for index, name in enumerate(names)
        ],
    )
    save_figure(fig, "11_rank_weight_sensitivity")


def main() -> None:
    configure_style()
    data = load_official_data()
    raw = read_json("raw_solution.json")
    supplier_analysis = read_json("supplier_analysis.json")
    split = read_json("transport_split_analysis.json")
    sensitivity = read_json("sensitivity_analysis.json")
    rank_sensitivity_data = read_json("rank_sensitivity.json")

    supplier_metric_distributions(data)
    supplier_top20_scores(supplier_analysis)
    material_capacity_distribution(data)
    problem2_weekly_orders(raw)
    problem2_transporter_load(raw)
    problem2_inventory(raw)
    problem3_material_mix(raw)
    problem3_transport_splitting(split)
    problem4_capacity(raw)
    sensitivity_stress_tests(sensitivity)
    rank_weight_sensitivity(rank_sensitivity_data)
    write_figure_contracts()
    qa_report = write_qa_report()

    generated = sorted(path.name for path in FIGURE_DIR.iterdir() if path.is_file())
    print(
        json.dumps(
            {
                "paper_figure_count": len(FIGURE_CONTRACTS),
                "top_level_artifact_count": len(generated),
                "source_data_count": len(list(SOURCE_DATA_DIR.glob("*.csv"))),
                "qa_passed": qa_report["passed"],
                "files": generated,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
