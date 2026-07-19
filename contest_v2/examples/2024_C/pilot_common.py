"""2024-C 试点的资源预算、稳定输出与公共评价函数。"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np


MEMORY_LIMIT_BYTES = 4 * 1024**3


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_memory_guard(limit_bytes: int = MEMORY_LIMIT_BYTES) -> tuple[threading.Event, dict[str, int]]:
    """监控当前求解进程；超预算时只终止该隔离子进程。"""
    import psutil

    stop = threading.Event()
    record = {"peak_rss_bytes": 0, "limit_bytes": limit_bytes}

    def monitor() -> None:
        process = psutil.Process(os.getpid())
        while not stop.wait(0.1):
            rss = process.memory_info().rss + sum((child.memory_info().rss for child in process.children(recursive=True)), 0)
            record["peak_rss_bytes"] = max(record["peak_rss_bytes"], rss)
            if rss > limit_bytes:
                os._exit(137)

    threading.Thread(target=monitor, daemon=True).start()
    return stop, record


def configure_solver(core, *, seconds: int, gap: float = 0.01) -> None:
    original = core.SparseMILP.solve

    def solve(self, time_limit=seconds, gap=gap):
        return original(self, time_limit=seconds, gap=gap)

    core.SparseMILP.solve = solve


def risk_stats(values) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    p05 = float(np.quantile(array, 0.05))
    tail = array[array <= p05]
    return {
        "mean": float(array.mean()),
        "std": float(array.std(ddof=1)),
        "p05": p05,
        "cvar05": float(tail.mean()),
        "min": float(array.min()),
        "max": float(array.max()),
        "loss_probability": float(np.mean(array < 0)),
    }


def area_by_crop(assignments) -> dict[int, float]:
    result: dict[int, float] = {}
    for item in assignments:
        crop = int(item["crop_id"])
        result[crop] = result.get(crop, 0.0) + float(item["area_mu"])
    return result


def resource_usage(data, assignments) -> list[dict[str, float | int | str]]:
    rows = []
    for year in range(2024, 2031):
        for plot_type in sorted({item["type"] for item in data.plots.values()}):
            plots = {name for name, item in data.plots.items() if item["type"] == plot_type}
            planted = sum(float(item["area_mu"]) for item in assignments if int(item["year"]) == year and item["plot_id"] in plots)
            capacity = sum(float(data.plots[name]["area"]) for name in plots)
            # 图示口径按“地块面积×可用季次数”归一化；水浇地蔬菜模式同样有两季。
            multiplier = 2 if plot_type in {"水浇地", "普通大棚", "智慧大棚"} else 1
            rows.append({"year": year, "plot_type": plot_type, "planted_area_mu": planted, "nominal_capacity_mu": capacity * multiplier, "utilisation": planted / (capacity * multiplier)})
    return rows


def elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 6)
