"""从官方附件真实求解 2024-C Q1 两种销售情形。"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


QUESTION_DIR = Path(__file__).resolve().parent
RUN_DIR = QUESTION_DIR.parents[1]
sys.path.insert(0, str(RUN_DIR / "shared"))
import pilot_common
import solver_core as core


def save_figure(fig, name: str) -> None:
    output = QUESTION_DIR / "figures" / name
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    started = time.perf_counter()
    stop, memory = pilot_common.start_memory_guard()
    core.ROOT = RUN_DIR
    core.MATERIALS = RUN_DIR / "materials"
    pilot_common.configure_solver(core, seconds=60, gap=0.01)
    data = core.ProblemData()
    result_dir = QUESTION_DIR / "results"
    artifacts = result_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    candidate_plans = {}
    candidate_solvers = {}
    reuse = os.environ.get("Q1_REUSE_CANDIDATES") == "1"
    for label, alpha in (("q1_waste", 0.0), ("q1_discount", 0.5)):
        candidate_path = artifacts / f"candidate_{label}.json"
        legacy_path = artifacts / f"{label}_plan.json"
        if reuse and (candidate_path.is_file() or legacy_path.is_file()):
            record = json.loads((candidate_path if candidate_path.is_file() else legacy_path).read_text(encoding="utf-8"))
            candidate_plans[label] = record["assignments"]
            candidate_solvers[label] = record["solver"]
        else:
            factors = core.deterministic_factors("q1", data)
            candidate_plans[label], candidate_solvers[label] = core.build_and_solve(data, factors, alpha, label)
        if not core.validate_solution(data, candidate_plans[label])["feasible"]:
            raise RuntimeError(f"{label} 候选约束检查失败")
        pilot_common.write_json(candidate_path, {"candidate_id": label, "assignments": candidate_plans[label], "solver": candidate_solvers[label]})

    plans = {}
    evaluations = {}
    validations = {}
    solvers = {}
    for target, alpha in (("q1_waste", 0.0), ("q1_discount", 0.5)):
        factors = core.deterministic_factors("q1", data)
        candidate_values = {source: core.evaluate_solution(data, plan, factors, alpha) for source, plan in candidate_plans.items()}
        selected = max(candidate_values, key=lambda source: candidate_values[source]["objective"])
        plans[target] = candidate_plans[selected]
        evaluations[target] = candidate_values[selected]
        validations[target] = core.validate_solution(data, plans[target])
        solvers[target] = {**candidate_solvers[selected], "selected_candidate": selected, "target_objective": target, "target_gap_applicable": selected == target, "candidate_objectives": {key: value["objective"] for key, value in candidate_values.items()}}
        pilot_common.write_json(artifacts / f"{target}_plan.json", {"scenario_id": target, "assignments": plans[target], "objective_reported": evaluations[target]["objective"], "solver": solvers[target]})

    core.fill_template(RUN_DIR / "materials/templates/result1_1.xlsx", RUN_DIR / "official/result1_1.xlsx", plans["q1_waste"], data)
    core.fill_template(RUN_DIR / "materials/templates/result1_2.xlsx", RUN_DIR / "official/result1_2.xlsx", plans["q1_discount"], data)

    scenario_rows = []
    yearly_rows = []
    crop_rows = []
    for label in plans:
        scenario_rows.append({"scenario": label, "profit_yuan": evaluations[label]["objective"], "source_mip_gap": solvers[label]["mip_gap"], "target_gap_applicable": solvers[label]["target_gap_applicable"], "selected_candidate": solvers[label]["selected_candidate"], "assignment_count": len(plans[label])})
        for year, item in evaluations[label]["yearly"].items():
            yearly_rows.append({"scenario": label, "year": year, **item})
        for crop, area in pilot_common.area_by_crop(plans[label]).items():
            crop_rows.append({"scenario": label, "crop_id": crop, "crop_name": data.crops[crop]["name"], "area_mu": area})
    resource_rows = pilot_common.resource_usage(data, plans["q1_waste"])
    tables = result_dir / "tables"
    pd.DataFrame(scenario_rows).to_csv(tables / "scenario_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(yearly_rows).to_csv(tables / "yearly_profit.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(crop_rows).to_csv(tables / "crop_area.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(resource_rows).to_csv(tables / "resource_usage.csv", index=False, encoding="utf-8-sig")

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 9})
    colors = ["#0072B2", "#D55E00"]
    fig, ax = plt.subplots(figsize=(5.8, 3.5))
    ax.bar(["超产浪费", "超产半价"], [evaluations[x]["objective"] / 1e6 for x in plans], color=colors)
    ax.set_ylabel("七年利润（百万元）"); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "scenario_profit")
    fig, ax = plt.subplots(figsize=(6.4, 3.7))
    for (label, text, color, marker) in (("q1_waste", "超产浪费", colors[0], "o"), ("q1_discount", "超产半价", colors[1], "s")):
        ax.plot(range(2024, 2031), [evaluations[label]["yearly"][year]["profit"] / 1e6 for year in range(2024, 2031)], label=text, color=color, marker=marker)
    ax.set(xlabel="年份", ylabel="年度利润（百万元）"); ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "yearly_profit")
    crop_frame = pd.DataFrame(crop_rows)
    top = crop_frame.groupby(["crop_id", "crop_name"], as_index=False).area_mu.sum().nlargest(10, "area_mu")
    ids = top.crop_id.tolist(); names = [f"{row.crop_name}({row.crop_id})" for row in top.itertuples()]
    fig, ax = plt.subplots(figsize=(6.4, 4.3)); width = 0.38; positions = list(range(len(ids)))
    for offset, (label, text, color) in zip((-width/2, width/2), (("q1_waste", "超产浪费", colors[0]), ("q1_discount", "超产半价", colors[1]))):
        values = [crop_frame[(crop_frame.scenario == label) & (crop_frame.crop_id == crop)].area_mu.sum() for crop in ids]
        ax.barh([p + offset for p in positions], values, height=width, label=text, color=color)
    ax.set_yticks(positions, names); ax.set_xlabel("七年累计种植面积（亩）"); ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "crop_area")
    resource = pd.DataFrame(resource_rows)
    pivot = resource.pivot(index="year", columns="plot_type", values="utilisation")
    fig, ax = plt.subplots(figsize=(6.4, 3.8)); pivot.plot(ax=ax, marker="o", colormap="viridis")
    ax.set(xlabel="年份", ylabel="名义资源利用率"); ax.legend(title="土地类型", frameon=False, ncol=2, fontsize=7); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "resource_usage")

    stop.set()
    max_violation = max(float(item["max_violation"]) for item in validations.values())
    max_gap = max(float(item["mip_gap"]) for item in solvers.values())
    result = {
        "question_id": "q1",
        "status": "complete",
        "metrics": {
            "waste_profit": {"value": evaluations["q1_waste"]["objective"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "discount_profit": {"value": evaluations["q1_discount"]["objective"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "max_constraint_violation": {"value": max_violation, "unit": "亩", "format": {"scale": 1, "decimals": 6, "suffix": "亩"}},
            "max_mip_gap": {"value": max_gap, "unit": "", "format": {"scale": 0.01, "decimals": 2, "suffix": "%"}},
        },
        "check_requests": [{"id": check, "kind": check} for check in ("hard_constraints", "objective_recalculation", "excel_readback", "sales_scenarios", "mip_gap_disclosure", "body_metric_binding")],
        "tables": [{"path": f"questions/q1/results/tables/{name}"} for name in ("scenario_summary.csv", "yearly_profit.csv", "crop_area.csv", "resource_usage.csv")],
        "figures": [{"path": f"questions/q1/figures/{name}.png"} for name in ("scenario_profit", "yearly_profit", "crop_area", "resource_usage")],
        "attachments": [{"path": "official/result1_1.xlsx"}, {"path": "official/result1_2.xlsx"}],
        "solver": {key: solvers[key] for key in solvers},
        "warnings": ["非零 MIP gap 时仅支持时限内可行方案表述", "跨候选择优方案若非由目标情形直接求解，则源 MIP gap 不构成该目标的最优性界"],
        "runtime": {"elapsed_seconds": pilot_common.elapsed(started), **memory},
    }
    pilot_common.write_json(result_dir / "result.json", result)
    pilot_common.write_json(RUN_DIR / "metrics/q1_runtime.json", result["runtime"])
    print(json.dumps({"status": "Q1_RESULT_READY", "metrics": result["metrics"], "runtime": result["runtime"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
