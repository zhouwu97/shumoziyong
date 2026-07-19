"""执行 2024-C Q2 的风险情景重规划、稳定性评估与正式结果导出。"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


QUESTION_DIR = Path(__file__).resolve().parent
RUN_DIR = QUESTION_DIR.parents[1]
sys.path.insert(0, str(RUN_DIR / "shared"))
import pilot_common
import solver_core as core


TRAIN_SEEDS = (20240721, 20240722, 20240726)
CANDIDATE_SEED = 20240723
FINAL_SEED = 20240724
BOOTSTRAP_SEED = 20240725
RISK_WEIGHT = 0.25
TAIL_PROBABILITY = 0.10
TRAIN_SCENARIOS = 64
CANDIDATE_SCENARIOS = 512
FINAL_SCENARIOS = 2048


def save_figure(fig, name: str) -> None:
    output = QUESTION_DIR / "figures" / name
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def cvar(values, probability: float) -> float:
    array = np.asarray(values, dtype=float)
    cutoff = float(np.quantile(array, probability))
    return float(array[array <= cutoff].mean())


def utility(values, weight: float = RISK_WEIGHT) -> float:
    array = np.asarray(values, dtype=float)
    return float((1 - weight) * array.mean() + weight * cvar(array, TAIL_PROBABILITY))


def bootstrap_intervals(values, repeats: int = 600) -> dict[str, tuple[float, float]]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    estimates = {"mean": [], "p05": [], "cvar05": []}
    for _ in range(repeats):
        sample = rng.choice(array, size=array.size, replace=True)
        stats = pilot_common.risk_stats(sample)
        for key in estimates:
            estimates[key].append(stats[key])
    return {key: tuple(float(x) for x in np.quantile(items, [0.025, 0.975])) for key, items in estimates.items()}


def assignment_map(assignments) -> dict[tuple, float]:
    result = defaultdict(float)
    for item in assignments:
        key = (int(item["year"]), str(item["plot_id"]), str(item["season"]), int(item["crop_id"]))
        result[key] += float(item["area_mu"])
    return dict(result)


def load_frozen_support() -> tuple[set[tuple], list[str]]:
    sources = [
        RUN_DIR / "questions/q1/results/artifacts/candidate_q1_waste.json",
        RUN_DIR / "questions/q1/results/artifacts/candidate_q1_discount.json",
        RUN_DIR / "questions/q1/results/artifacts/q1_waste_plan.json",
        RUN_DIR / "questions/q1/results/artifacts/q1_discount_plan.json",
        *sorted((QUESTION_DIR / "results/artifacts").glob("independent_mean_*.json")),
    ]
    support, used = set(), []
    for path in sources:
        if not path.is_file():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        assignments = record.get("assignments", [])
        if not assignments:
            continue
        used.append(path.name)
        support.update((int(x["year"]), str(x["plot_id"]), str(x["season"]), int(x["crop_id"])) for x in assignments)
    if not support:
        raise RuntimeError("Q2 冻结支持集为空")
    return support, used


def main() -> int:
    started = time.perf_counter()
    stop, memory = pilot_common.start_memory_guard()
    core.ROOT = RUN_DIR
    core.MATERIALS = RUN_DIR / "materials"
    pilot_common.configure_solver(core, seconds=300, gap=0.02)
    data = core.ProblemData()
    result_dir = QUESTION_DIR / "results"
    artifacts = result_dir / "artifacts"
    tables = result_dir / "tables"
    artifacts.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    support, support_sources = load_frozen_support()
    pilot_common.write_json(artifacts / "support_snapshot.json", {
        "frozen_before_reoptimisation": True,
        "sources": support_sources,
        "support_size": len(support),
        "keys": [list(key) for key in sorted(support)],
    })

    candidates, solver_meta = {}, {}
    labels = ("风险规划方案 A", "风险规划方案 B", "风险规划方案 C")
    for label, seed in zip(labels, TRAIN_SEEDS):
        factors = core.random_factors(TRAIN_SCENARIOS, seed, correlated=False)
        candidate_id = f"risk_saa_{chr(97 + len(candidates))}"
        candidates[candidate_id], solver_meta[candidate_id] = core.build_and_solve(
            data, factors, 0.0, label, support_keys=support,
            risk_weight=RISK_WEIGHT, tail_probability=TAIL_PROBABILITY,
        )
        validation = core.validate_solution(data, candidates[candidate_id])
        if not validation["feasible"]:
            raise RuntimeError(f"{label} 约束检查失败")
        pilot_common.write_json(artifacts / f"{candidate_id}.json", {
            "candidate_id": candidate_id, "academic_label": label, "training_seed": seed,
            "training_scenarios": TRAIN_SCENARIOS, "assignments": candidates[candidate_id],
            "solver": solver_meta[candidate_id],
        })

    baseline_record = json.loads((RUN_DIR / "questions/q1/results/artifacts/q1_waste_plan.json").read_text(encoding="utf-8"))
    baseline_plan = baseline_record["assignments"]
    candidate_factors = core.random_factors(CANDIDATE_SCENARIOS, CANDIDATE_SEED, correlated=False)
    candidate_rows = []
    for candidate_id, plan in {**candidates, "q1_baseline": baseline_plan}.items():
        values = core.sample_profits(data, plan, candidate_factors)
        stats = pilot_common.risk_stats(values)
        candidate_rows.append({
            "candidate_id": candidate_id,
            "academic_label": labels[ord(candidate_id[-1]) - 97] if candidate_id.startswith("risk_saa_") else "问题一确定性基准",
            **stats, "cvar10": cvar(values, TAIL_PROBABILITY), "risk_utility": utility(values),
        })
    selected = max((row for row in candidate_rows if row["candidate_id"].startswith("risk_saa_")), key=lambda row: row["risk_utility"])["candidate_id"]
    selected_plan = candidates[selected]
    selected_label = next(row["academic_label"] for row in candidate_rows if row["candidate_id"] == selected)

    selected_map, baseline_map = assignment_map(selected_plan), assignment_map(baseline_plan)
    difference_rows = []
    for key in sorted(set(selected_map) | set(baseline_map)):
        change = selected_map.get(key, 0.0) - baseline_map.get(key, 0.0)
        if abs(change) <= 1e-6:
            continue
        year, plot, season, crop = key
        difference_rows.append({
            "year": year, "plot_id": plot, "plot_type": data.plots[plot]["type"], "season": season,
            "crop_id": crop, "crop_name": data.crops[crop]["name"],
            "q1_area_mu": baseline_map.get(key, 0.0), "q2_area_mu": selected_map.get(key, 0.0), "change_mu": change,
        })
    if not difference_rows:
        raise RuntimeError("Q2 风险重规划与 Q1 基准完全相同，不满足里程碑")

    final_factors = core.random_factors(FINAL_SCENARIOS, FINAL_SEED, correlated=False)
    np.savez_compressed(result_dir / "final_evaluation_factors.npz", **{key: final_factors[key] for key in ("demand", "yield", "cost", "price")})
    final_values = core.sample_profits(data, selected_plan, final_factors)
    baseline_values = core.sample_profits(data, baseline_plan, final_factors)
    final_stats = pilot_common.risk_stats(final_values)
    baseline_stats = pilot_common.risk_stats(baseline_values)
    paired = final_values - baseline_values
    intervals = bootstrap_intervals(final_values)

    convergence_rows = []
    for count in (256, 512, 1024, FINAL_SCENARIOS):
        for strategy, values in (("Q2 风险方案", final_values[:count]), ("Q1 确定性基准", baseline_values[:count])):
            stats = pilot_common.risk_stats(values)
            convergence_rows.append({"sample_count": count, "strategy": strategy, **stats})

    weight_rows = []
    for weight in (0.0, 0.10, 0.25, 0.50):
        scored = []
        for row in candidate_rows:
            value = (1 - weight) * row["mean"] + weight * row["cvar10"]
            scored.append((value, row["academic_label"]))
        best_value, best_label = max(scored)
        weight_rows.append({"risk_weight": weight, "selected_label": best_label, "best_utility_yuan": best_value})

    uncertainty_rows = [
        {"variable": "普通作物销量", "distribution": "U(0.95,1.05)×2023销量", "time_rule": "逐年独立"},
        {"variable": "小麦/玉米销量", "distribution": "年增长率U(0.05,0.10)", "time_rule": "逐年复合"},
        {"variable": "亩产量", "distribution": "U(0.90,1.10)×基准亩产", "time_rule": "逐年独立"},
        {"variable": "种植成本", "distribution": "年增长率U(0.04,0.06)", "time_rule": "逐年复合"},
        {"variable": "蔬菜价格", "distribution": "年增长率U(0.04,0.06)", "time_rule": "逐年复合"},
        {"variable": "食用菌价格", "distribution": "题面给定下降区间", "time_rule": "逐年复合/羊肚菌固定5%"},
    ]

    core.fill_template(RUN_DIR / "materials/templates/result2.xlsx", RUN_DIR / "official/result2.xlsx", selected_plan, data)
    pd.DataFrame(candidate_rows).to_csv(tables / "candidate_evaluation.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"sample_id": range(FINAL_SCENARIOS), "q2_profit_yuan": final_values, "q1_profit_yuan": baseline_values, "paired_difference_yuan": paired}).to_csv(tables / "final_sample_profits.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(difference_rows).sort_values("change_mu", key=lambda x: x.abs(), ascending=False).to_csv(tables / "plan_difference.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(convergence_rows).to_csv(tables / "sample_convergence.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(weight_rows).to_csv(tables / "risk_weight_sensitivity.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(uncertainty_rows).to_csv(tables / "uncertainty_model.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"metric": key, "lower_95": value[0], "upper_95": value[1]} for key, value in intervals.items()]).to_csv(tables / "bootstrap_intervals.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{ "candidate_id": key, **value } for key, value in solver_meta.items()]).to_csv(tables / "solver_evidence.csv", index=False, encoding="utf-8-sig")

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 9})
    colors = ["#0072B2", "#009E73", "#CC79A7", "#777777"]
    frame = pd.DataFrame(candidate_rows)
    fig, ax = plt.subplots(figsize=(6.2, 3.7))
    ax.bar(frame.academic_label, frame.risk_utility / 1e6, color=colors)
    ax.set_ylabel("风险效用（百万元）"); ax.tick_params(axis="x", rotation=12); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "candidate_scores")
    fig, ax = plt.subplots(figsize=(6.2, 3.7))
    ax.hist(paired / 1e4, bins=35, color=colors[0], alpha=0.8); ax.axvline(0, color="black", linewidth=0.8)
    ax.set(xlabel="Q2 风险方案相对 Q1 的配对利润差（万元）", ylabel="样本数"); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "held_out_distribution")
    conv = pd.DataFrame(convergence_rows)
    fig, ax = plt.subplots(figsize=(6.2, 3.7))
    for strategy, group in conv.groupby("strategy"):
        ax.plot(group.sample_count, group.cvar05 / 1e6, marker="o", label=strategy)
    ax.set(xlabel="情景样本量", ylabel="5% CVaR（百万元）"); ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "sample_convergence")

    stop.set()
    max_gap = max(float(value["mip_gap"]) for value in solver_meta.values())
    if max_gap > 0.10:
        raise RuntimeError(f"Q2 最大 MIP gap={max_gap:.3%}，超过冻结的 10% 里程碑")
    result = {
        "question_id": "q2", "status": "complete",
        "metrics": {
            "final_mean_profit": {"value": final_stats["mean"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "final_std_profit": {"value": final_stats["std"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "final_p05_profit": {"value": final_stats["p05"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "final_cvar05_profit": {"value": final_stats["cvar05"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "baseline_mean_profit": {"value": baseline_stats["mean"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "paired_mean_improvement": {"value": float(paired.mean()), "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "relative_mean_improvement": {"value": float(paired.mean() / abs(baseline_stats["mean"])), "unit": "", "format": {"scale": 0.01, "decimals": 2, "suffix": "%"}},
            "plan_l1_change": {"value": float(sum(abs(row["change_mu"]) for row in difference_rows)), "unit": "亩", "format": {"scale": 1, "decimals": 2, "suffix": "亩"}},
            "max_mip_gap": {"value": max_gap, "unit": "", "format": {"scale": 0.01, "decimals": 2, "suffix": "%"}},
            "final_sample_count": {"value": FINAL_SCENARIOS, "unit": "个", "format": {"scale": 1, "decimals": 0, "suffix": "个"}},
        },
        "check_requests": [{"id": check, "kind": check} for check in ("hard_constraints", "excel_readback", "held_out_evaluation", "sample_separation", "plan_reoptimisation", "solver_evidence", "uncertainty_audit", "stability_analysis", "body_metric_binding")],
        "tables": [{"path": f"questions/q2/results/tables/{name}"} for name in ("candidate_evaluation.csv", "final_sample_profits.csv", "plan_difference.csv", "sample_convergence.csv", "risk_weight_sensitivity.csv", "uncertainty_model.csv", "bootstrap_intervals.csv", "solver_evidence.csv")],
        "figures": [{"path": f"questions/q2/figures/{name}.png"} for name in ("candidate_scores", "held_out_distribution", "sample_convergence")],
        "attachments": [{"path": "official/result2.xlsx"}],
        "solver": {"selected_candidate": selected, "selected_label": selected_label, "candidates": solver_meta, "risk_weight": RISK_WEIGHT, "tail_probability": TAIL_PROBABILITY},
        "warnings": ["随机分布为题面区间内的决策假设，不是历史数据拟合", "最优性结论限定于求解前冻结的支持集"],
        "runtime": {"elapsed_seconds": pilot_common.elapsed(started), **memory},
    }
    pilot_common.write_json(artifacts / "selected_plan.json", {"candidate_id": selected, "academic_label": selected_label, "assignments": selected_plan, "candidate_evaluation": candidate_rows, "bootstrap_intervals": intervals})
    pilot_common.write_json(artifacts / "sample_split.json", {"training": {"seeds": list(TRAIN_SEEDS), "scenarios_per_seed": TRAIN_SCENARIOS}, "candidate_evaluation": {"seed": CANDIDATE_SEED, "scenarios": CANDIDATE_SCENARIOS}, "final_evaluation": {"seed": FINAL_SEED, "scenarios": FINAL_SCENARIOS}, "bootstrap_seed": BOOTSTRAP_SEED, "sets_disjoint_by_seed": True})
    pilot_common.write_json(result_dir / "result.json", result)
    pilot_common.write_json(RUN_DIR / "metrics/q2_runtime.json", result["runtime"])
    print(json.dumps({"status": "Q2_RESULT_READY", "selected": selected_label, "metrics": result["metrics"], "runtime": result["runtime"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
