"""2024-C 官方附件的规范数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


YEARS = tuple(range(2024, 2031))
DRYLAND_TYPES = frozenset({"平旱地", "梯田", "山坡地"})
GREENHOUSE_TYPES = frozenset({"普通大棚", "智慧大棚"})
LEGUME_CROP_IDS = frozenset({1, 2, 3, 4, 5, 17, 18, 19})


@dataclass(frozen=True)
class SourceCell:
    """规范字段对应的官方工作簿单元格。"""

    workbook: str
    sheet: str
    row: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Plot:
    plot_id: str
    plot_type: str
    area_mu: float
    source: SourceCell


@dataclass(frozen=True)
class Crop:
    crop_id: int
    name: str
    crop_type: str
    is_legume: bool
    source: SourceCell


@dataclass(frozen=True)
class Planting2023:
    plot_id: str
    crop_id: int
    season: str
    area_mu: float
    source: SourceCell


@dataclass(frozen=True)
class CropStat:
    crop_id: int
    plot_type: str
    season: str
    yield_jin_per_mu: float
    cost_yuan_per_mu: float
    price_low_yuan_per_jin: float
    price_high_yuan_per_jin: float
    source: SourceCell

    @property
    def price_mid_yuan_per_jin(self) -> float:
        return (self.price_low_yuan_per_jin + self.price_high_yuan_per_jin) / 2.0


@dataclass(frozen=True)
class ProblemData:
    """求解器与 Validator 共享的只读官方事实，不包含求解逻辑。"""

    plots: dict[str, Plot]
    crops: dict[int, Crop]
    planting_2023: tuple[Planting2023, ...]
    statistics: dict[tuple[int, str, str], CropStat]
    expected_sales_2023: dict[tuple[int, str], float]

    def seasons(self, plot_type: str) -> tuple[str, ...]:
        if plot_type in DRYLAND_TYPES:
            return ("单季",)
        if plot_type == "水浇地":
            return ("单季", "第一季", "第二季")
        if plot_type in GREENHOUSE_TYPES:
            return ("第一季", "第二季")
        raise KeyError(f"未知地块类型：{plot_type}")

    def eligible_crops(self, plot_type: str, season: str) -> tuple[int, ...]:
        """按附件 1 的七条种植说明返回允许集合。"""
        if plot_type in DRYLAND_TYPES:
            return tuple(range(1, 16)) if season == "单季" else ()
        if plot_type == "水浇地":
            if season == "单季":
                return (16,)
            if season == "第一季":
                return tuple(range(17, 35))
            if season == "第二季":
                return (35, 36, 37)
        if plot_type == "普通大棚":
            if season == "第一季":
                return tuple(range(17, 35))
            if season == "第二季":
                return tuple(range(38, 42))
        if plot_type == "智慧大棚" and season in {"第一季", "第二季"}:
            return tuple(range(17, 35))
        return ()

    def stat(self, crop_id: int, plot_type: str, season: str) -> CropStat:
        key = (crop_id, plot_type, season)
        if key in self.statistics:
            return self.statistics[key]
        # 附件 2 明确说明智慧大棚第一季沿用普通大棚第一季参数。
        fallback = (crop_id, "普通大棚", season)
        if plot_type == "智慧大棚" and season == "第一季" and fallback in self.statistics:
            return self.statistics[fallback]
        raise KeyError(f"缺少作物统计参数：{key}")

    def history_for(self, plot_id: str, season: str | None = None) -> tuple[Planting2023, ...]:
        return tuple(
            item
            for item in self.planting_2023
            if item.plot_id == plot_id and (season is None or item.season == season)
        )

