"""本训练的公共数据加载、参数与序列化工具。

本模块只读取本轮复制的官方材料和本轮假设，不包含任何优化器或历史题解逻辑。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MATERIALS = ROOT / "materials"
RESULTS = ROOT / "results"
OUTPUTS = ROOT / "outputs"
FIGURES = ROOT / "figures"

DEMAND_BASE = 28_200.0
HORIZON = 24
TRANSPORTER_CAPACITY = 6_000.0
SAFETY_WEEKS = 2
PURCHASE_COST = {"A": 1.20, "B": 1.10, "C": 1.00}
RAW_PER_PRODUCT = {"A": 0.60, "B": 0.66, "C": 0.72}
TOLERANCE = 1e-6


def json_ready(value: Any) -> Any:
    """将 numpy、pandas 标量递归转换为稳定的 JSON 基础类型。"""
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_ready(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    """以 UTF-8 和固定缩进写入结果，便于人工复算。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    """流式计算文件哈希，避免将 Excel/PDF 整体载入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _positive_quantile(values: np.ndarray, quantile: float) -> float:
    positive = values[values > 0]
    return float(np.quantile(positive, quantile)) if positive.size else 0.0


def load_official_data() -> dict[str, Any]:
    """读取官方 Excel，并构造不依赖求解器的供应与损耗统计量。

    ``regular_order_capacity`` 是本轮唯一的未来供货上限：历史中发生下单时的
    非零供货均值，乘以该供应商在下单周实现非零供货的概率。它表达的是常规重复
    下单下的期望可供货量；它不是保证供货量，压力测试会单独处理这一不确定性。
    """
    attachment1 = MATERIALS / "附件1 近5年402家供应商的相关数据.xlsx"
    attachment2 = MATERIALS / "附件2 近5年8家转运商的相关数据.xlsx"
    order_frame = pd.read_excel(attachment1, sheet_name="企业的订货量（m³）")
    supply_frame = pd.read_excel(attachment1, sheet_name="供应商的供货量（m³）")
    loss_frame = pd.read_excel(attachment2, sheet_name="运输损耗率（%）")

    week_names = [str(column) for column in order_frame.columns[2:]]
    supplier_ids = supply_frame.iloc[:, 0].astype(str).tolist()
    material_types = supply_frame.iloc[:, 1].astype(str).tolist()
    transporter_ids = loss_frame.iloc[:, 0].astype(str).tolist()
    orders = order_frame.iloc[:, 2:].to_numpy(dtype=float)
    historical_supply = supply_frame.iloc[:, 2:].to_numpy(dtype=float)
    historical_loss_percent = loss_frame.iloc[:, 1:].to_numpy(dtype=float)

    if supplier_ids != order_frame.iloc[:, 0].astype(str).tolist():
        raise ValueError("附件1两张工作表的供应商 ID 顺序不一致")
    if orders.shape != historical_supply.shape or orders.shape[1] != 240:
        raise ValueError("附件1的周序列维度不符合题面")
    if historical_loss_percent.shape != (8, 240):
        raise ValueError("附件2的转运商或周序列维度不符合题面")

    ordered_weeks = (orders > 0).sum(axis=1)
    positive_supply_weeks = (historical_supply > 0).sum(axis=1)
    positive_supply_mean = np.array(
        [
            row[row > 0].mean() if np.any(row > 0) else 0.0
            for row in historical_supply
        ],
        dtype=float,
    )
    service_probability = np.divide(
        positive_supply_weeks,
        ordered_weeks,
        out=np.zeros_like(positive_supply_weeks, dtype=float),
        where=ordered_weeks > 0,
    )
    regular_order_capacity = positive_supply_mean * service_probability
    total_ordered = orders.sum(axis=1)
    total_supplied = historical_supply.sum(axis=1)
    fulfilment_ratio = np.divide(
        total_supplied,
        total_ordered,
        out=np.zeros_like(total_supplied, dtype=float),
        where=total_ordered > 0,
    )
    # 订货量换算不假设供应商会稳定超额供货，故将兑现率截断为 1。
    order_response_ratio = np.minimum(fulfilment_ratio, 1.0)

    nonzero_loss_means = np.array(
        [row[row > 0].mean() if np.any(row > 0) else 0.0 for row in historical_loss_percent],
        dtype=float,
    ) / 100.0
    nonzero_loss_p90 = np.array(
        [
            np.quantile(row[row > 0], 0.90) if np.any(row > 0) else 0.0
            for row in historical_loss_percent
        ],
        dtype=float,
    ) / 100.0

    raw_per_product = np.array([RAW_PER_PRODUCT[item] for item in material_types], dtype=float)
    unit_cost = np.array([PURCHASE_COST[item] for item in material_types], dtype=float)
    supplier_metrics: list[dict[str, Any]] = []
    for index, supplier_id in enumerate(supplier_ids):
        row_supply = historical_supply[index]
        row_order = orders[index]
        positive = row_supply[row_supply > 0]
        ordered = row_order > 0
        conditional_ratio = np.divide(
            row_supply[ordered],
            row_order[ordered],
            out=np.zeros(int(ordered.sum()), dtype=float),
            where=row_order[ordered] > 0,
        )
        supplier_metrics.append(
            {
                "supplier_id": supplier_id,
                "material_type": material_types[index],
                "ordered_weeks": int(ordered_weeks[index]),
                "positive_supply_weeks": int(positive_supply_weeks[index]),
                "service_probability": float(service_probability[index]),
                "mean_supply_all_weeks": float(row_supply.mean()),
                "mean_supply_positive_weeks": float(positive_supply_mean[index]),
                "supply_p25_positive_weeks": _positive_quantile(row_supply, 0.25),
                "supply_p50_positive_weeks": _positive_quantile(row_supply, 0.50),
                "supply_p90_positive_weeks": _positive_quantile(row_supply, 0.90),
                "supply_cv_positive_weeks": float(positive.std(ddof=0) / positive.mean())
                if positive.size and positive.mean() > 0
                else None,
                "weighted_fulfilment_ratio": float(fulfilment_ratio[index]),
                "conditional_ratio_median": float(np.median(conditional_ratio))
                if conditional_ratio.size
                else None,
                "regular_order_capacity": float(regular_order_capacity[index]),
                "product_equivalent_capacity_before_loss": float(
                    regular_order_capacity[index] / raw_per_product[index]
                ),
            }
        )

    return {
        "supplier_ids": supplier_ids,
        "material_types": material_types,
        "transporter_ids": transporter_ids,
        "week_names": week_names,
        "orders_history": orders,
        "supply_history": historical_supply,
        "loss_history_percent": historical_loss_percent,
        "loss_mean": nonzero_loss_means,
        "loss_p90": nonzero_loss_p90,
        "ordered_weeks": ordered_weeks,
        "positive_supply_weeks": positive_supply_weeks,
        "service_probability": service_probability,
        "regular_order_capacity": regular_order_capacity,
        "fulfilment_ratio": fulfilment_ratio,
        "order_response_ratio": order_response_ratio,
        "raw_per_product": raw_per_product,
        "unit_cost": unit_cost,
        "supplier_metrics": supplier_metrics,
    }


def base_assumptions() -> dict[str, Any]:
    """返回模型和检查器共同读取的数值合同。"""
    return {
        "training_id": "engineering-optimization-round2-retry1",
        "horizon_weeks": HORIZON,
        "base_weekly_production_m3": DEMAND_BASE,
        "safety_stock_weeks": SAFETY_WEEKS,
        "initial_inventory_product_equivalent_m3": SAFETY_WEEKS * DEMAND_BASE,
        "terminal_inventory_lower_bound_product_equivalent_m3": SAFETY_WEEKS * DEMAND_BASE,
        "raw_m3_per_product_m3": RAW_PER_PRODUCT,
        "relative_purchase_cost": PURCHASE_COST,
        "transporter_weekly_capacity_raw_m3": TRANSPORTER_CAPACITY,
        "future_supply_capacity": {
            "name": "regular_order_capacity",
            "formula": "mean(nonzero historical supply) * P(nonzero supply | historical order > 0)",
            "interpretation": "常规重复下单下的期望可供货上限，不是保证供货量",
        },
        "order_response": {
            "formula": "min(total historical supply / total historical order, 1)",
            "interpretation": "为避免依赖超额供货，订货量换算时不使用大于1的兑现率",
        },
        "transport_loss_forecast": {
            "formula": "mean(nonzero historical loss rate)",
            "zero_interpretation": "题面规定0表示未运输，不作为零损耗观测纳入均值",
        },
        "supplier_transporter_policy": "问题2将每个供应商每周至多一名转运商作为硬约束；问题3、4按题面‘尽量’的软语义统计并披露拆分。",
        "inventory_pooling": "A、B、C可替代生产，库存按可生产产品立方米等价量统一记账。",
        "decision_precision": "内部使用双精度；报告与检查容差为1e-6。",
    }
