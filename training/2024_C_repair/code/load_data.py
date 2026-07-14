"""从官方附件读取 2024-C 数据，并保留全部可追溯统计维度。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT.parents[1] / "official_materials" / "2024_C" / "attachments"
YEARS = tuple(range(2024, 2031))
LEGUMES = frozenset({1, 2, 3, 4, 5, 17, 18, 19})


def _clean_text(value: object) -> str:
    return str(value).replace(" ", "").strip()


def _midpoint(value: object) -> float:
    low, high = (float(item) for item in str(value).split("-"))
    return (low + high) / 2.0


@dataclass(frozen=True)
class ProblemData:
    """题面附件的规范化只读视图。"""

    plots: pd.DataFrame
    crops: pd.DataFrame
    history: pd.DataFrame
    statistics: pd.DataFrame
    demand_2023: dict[tuple[int, str, str], float]

    def eligible_crops(self, plot_type: str, slot: str) -> tuple[int, ...]:
        """按附件 1 返回给定地块类型与季次允许的作物编号。"""
        if plot_type in {"平旱地", "梯田", "山坡地"}:
            return tuple(range(1, 16)) if slot == "单季" else ()
        if plot_type == "水浇地":
            if slot == "单季":
                return (16,)
            if slot == "第一季":
                return tuple(range(17, 35))
            if slot == "第二季":
                return (35, 36, 37)
        if plot_type == "普通大棚":
            if slot == "第一季":
                return tuple(range(17, 35))
            if slot == "第二季":
                return tuple(range(38, 42))
        if plot_type == "智慧大棚" and slot in {"第一季", "第二季"}:
            return tuple(range(17, 35))
        return ()

    def slots(self, plot_type: str) -> tuple[str, ...]:
        if plot_type in {"平旱地", "梯田", "山坡地"}:
            return ("单季",)
        if plot_type == "水浇地":
            return ("单季", "第一季", "第二季")
        return ("第一季", "第二季")

    def stat_key(self, crop_id: int, plot_type: str, slot: str) -> tuple[int, str, str]:
        return (int(crop_id), plot_type, slot)

    def parameters(self, key: tuple[int, str, str]) -> tuple[float, float, float]:
        """返回亩产量、亩成本和中点销售价；处理官方给出的智慧棚继承规则。"""
        crop_id, plot_type, slot = key
        lookup_type = "普通大棚" if (plot_type, slot) == ("智慧大棚", "第一季") else plot_type
        row = self.statistics.loc[
            (self.statistics["作物编号"] == crop_id)
            & (self.statistics["地块类型"] == lookup_type)
            & (self.statistics["种植季次"] == slot)
        ]
        if len(row) != 1:
            raise KeyError(f"缺少官方统计参数：{key}")
        record = row.iloc[0]
        return (float(record["亩产量/斤"]), float(record["种植成本/(元/亩)"]), float(record["销售单价中点"]))

    def historical_last_crops(self, plot_id: str) -> set[int]:
        """按地块类型取 2023 最后实际有效季中的作物集合。"""
        plot_type = self.plots.loc[plot_id, "地块类型"]
        rows = self.history.loc[self.history["种植地块"] == plot_id]
        if rows.empty:
            return set()
        if plot_type == "水浇地":
            season = "第二季" if (rows["种植季次"] == "第二季").any() else "单季"
        elif plot_type in {"普通大棚", "智慧大棚"}:
            season = "第二季"
        else:
            season = "单季"
        return set(rows.loc[rows["种植季次"] == season, "作物编号"].astype(int))


def load_data() -> ProblemData:
    """读取附件 1、附件 2，绝不写回官方材料。"""
    attachment_1 = MATERIALS / "附件1.xlsx"
    attachment_2 = MATERIALS / "附件2.xlsx"
    plots = pd.read_excel(attachment_1, sheet_name="乡村的现有耕地").iloc[:54].copy()
    plots.columns = [str(column).strip() for column in plots.columns]
    plots["地块名称"] = plots["地块名称"].map(_clean_text)
    plots["地块类型"] = plots["地块类型"].map(_clean_text)
    plots["地块面积/亩"] = pd.to_numeric(plots["地块面积/亩"])
    plots = plots.set_index("地块名称", drop=False)

    crops = pd.read_excel(attachment_1, sheet_name="乡村种植的农作物").iloc[:41].copy()
    crops["作物编号"] = pd.to_numeric(crops["作物编号"]).astype(int)
    crops["作物名称"] = crops["作物名称"].map(_clean_text)
    crops["作物类型"] = crops["作物类型"].map(_clean_text)

    history = pd.read_excel(attachment_2, sheet_name="2023年的农作物种植情况").iloc[:87].copy()
    history["种植地块"] = history["种植地块"].ffill().map(_clean_text)
    history["作物编号"] = pd.to_numeric(history["作物编号"]).astype(int)
    history["种植面积/亩"] = pd.to_numeric(history["种植面积/亩"])
    history["种植季次"] = history["种植季次"].map(_clean_text)
    history["地块类型"] = history["种植地块"].map(plots["地块类型"])

    statistics = pd.read_excel(attachment_2, sheet_name="2023年统计的相关数据").iloc[:107].copy()
    statistics["作物编号"] = pd.to_numeric(statistics["作物编号"]).astype(int)
    for column in ("地块类型", "种植季次"):
        statistics[column] = statistics[column].map(_clean_text)
    for column in ("亩产量/斤", "种植成本/(元/亩)"):
        statistics[column] = pd.to_numeric(statistics[column])
    statistics["销售单价中点"] = statistics["销售单价/(元/斤)"].map(_midpoint)

    provisional = ProblemData(plots, crops, history, statistics, {})
    demand: dict[tuple[int, str, str], float] = {}
    for _, row in history.iterrows():
        key = provisional.stat_key(int(row["作物编号"]), str(row["地块类型"]), str(row["种植季次"]))
        yield_per_mu, _, _ = provisional.parameters(key)
        demand[key] = demand.get(key, 0.0) + float(row["种植面积/亩"]) * yield_per_mu
    return ProblemData(plots, crops, history, statistics, demand)
