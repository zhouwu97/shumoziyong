"""执行 2024-C Q3 的相关情景风险重规划与机制核验。"""

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


TRAIN_SEEDS = (20240731, 20240732, 20240736)
CANDIDATE_SEED = 20240733
FINAL_CORRELATED_SEED = 20240734
FINAL_INDEPENDENT_SEED = 20240735
RISK_WEIGHT = 0.25
TAIL_PROBABILITY = 0.10
TRAIN_SCENARIOS = 128
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


def utility(values) -> float:
    array = np.asarray(values, dtype=float)
    return float((1 - RISK_WEIGHT) * array.mean() + RISK_WEIGHT * cvar(array, TAIL_PROBABILITY))


def assignment_map(assignments) -> dict[tuple, float]:
    result = defaultdict(float)
    for item in assignments:
        key = (int(item["year"]), str(item["plot_id"]), str(item["season"]), int(item["crop_id"]))
        result[key] += float(item["area_mu"])
    return dict(result)


def pair_correlation(values: np.ndarray, pairs) -> float:
    return float(np.mean([
        np.corrcoef(values[:, :, left - 1].ravel(), values[:, :, right - 1].ravel())[0, 1]
        for left, right in pairs
    ]))


def load_frozen_support() -> tuple[set[tuple], list[str]]:
    sources = [
        RUN_DIR / "questions/q2/results/artifacts/selected_plan.json",
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
        raise RuntimeError("Q3 冻结支持集为空")
    return support, used


def main() -> int:
    started = time.perf_counter()
    stop, memory = pilot_common.start_memory_guard()
    core.ROOT = RUN_DIR
    core.MATERIALS = RUN_DIR / "materials"
    pilot_common.configure_solver(core, seconds=180, gap=0.001)
    data = core.ProblemData()
    result_dir = QUESTION_DIR / "results"
    artifacts = result_dir / "artifacts"
    tables = result_dir / "tables"
    artifacts.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    support, sources = load_frozen_support()
    pilot_common.write_json(artifacts / "support_snapshot.json", {
        "frozen_before_reoptimisation": True, "sources": sources, "support_size": len(support),
        "keys": [list(key) for key in sorted(support)],
    })

    candidates, solver_meta = {}, {}
    labels = ("相关风险方案 A", "相关风险方案 B", "相关风险方案 C")
    for label, seed in zip(labels, TRAIN_SEEDS):
        factors = core.random_factors(TRAIN_SCENARIOS, seed, correlated=True)
        candidate_id = f"correlated_risk_{chr(97 + len(candidates))}"
        candidates[candidate_id], solver_meta[candidate_id] = core.build_and_solve(
            data, factors, 0.0, label, support_keys=support,
            risk_weight=RISK_WEIGHT, tail_probability=TAIL_PROBABILITY,
            fixed_active_keys=support,
        )
        validation = core.validate_solution(data, candidates[candidate_id])
        if not validation["feasible"]:
            raise RuntimeError(f"{label} 约束检查失败")
        pilot_common.write_json(artifacts / f"{candidate_id}.json", {
            "candidate_id": candidate_id, "academic_label": label, "training_seed": seed,
            "training_scenarios": TRAIN_SCENARIOS, "assignments": candidates[candidate_id],
            "solver": solver_meta[candidate_id],
        })

    q2_record = json.loads((RUN_DIR / "questions/q2/results/artifacts/selected_plan.json").read_text(encoding="utf-8"))
    q2_plan = q2_record["assignments"]
    candidate_factors = core.random_factors(CANDIDATE_SCENARIOS, CANDIDATE_SEED, correlated=True)
    candidate_rows = []
    for candidate_id, plan in {**candidates, "q2_baseline": q2_plan}.items():
        values = core.sample_profits(data, plan, candidate_factors)
        stats = pilot_common.risk_stats(values)
        candidate_rows.append({
            "candidate_id": candidate_id,
            "academic_label": labels[ord(candidate_id[-1]) - 97] if candidate_id.startswith("correlated_risk_") else "问题二独立情景方案",
            **stats, "cvar10": cvar(values, TAIL_PROBABILITY), "risk_utility": utility(values),
        })
    selected = max((row for row in candidate_rows if row["candidate_id"].startswith("correlated_risk_")), key=lambda row: row["risk_utility"])["candidate_id"]
    selected_plan = candidates[selected]
    selected_label = next(row["academic_label"] for row in candidate_rows if row["candidate_id"] == selected)
    selected_utility = next(row["risk_utility"] for row in candidate_rows if row["candidate_id"] == selected)
    q2_utility = next(row["risk_utility"] for row in candidate_rows if row["candidate_id"] == "q2_baseline")
    if selected_utility <= q2_utility:
        raise RuntimeError("Q3 候选评价风险效用未高于 Q2，不满足里程碑")

    selected_map, q2_map = assignment_map(selected_plan), assignment_map(q2_plan)
    difference_rows = []
    for key in sorted(set(selected_map) | set(q2_map)):
        change = selected_map.get(key, 0.0) - q2_map.get(key, 0.0)
        if abs(change) <= 1e-6:
            continue
        year, plot, season, crop = key
        difference_rows.append({
            "year": year, "plot_id": plot, "plot_type": data.plots[plot]["type"], "season": season,
            "crop_id": crop, "crop_name": data.crops[crop]["name"],
            "q2_area_mu": q2_map.get(key, 0.0), "q3_area_mu": selected_map.get(key, 0.0), "change_mu": change,
        })
    if not difference_rows:
        raise RuntimeError("Q3 相关风险重规划与 Q2 方案完全相同，不满足里程碑")

    correlated = core.random_factors(FINAL_SCENARIOS, FINAL_CORRELATED_SEED, correlated=True)
    independent = core.random_factors(FINAL_SCENARIOS, FINAL_INDEPENDENT_SEED, correlated=False)
    np.savez_compressed(
        result_dir / "final_evaluation_factors.npz",
        **{f"correlated_{key}": correlated[key] for key in ("demand", "yield", "cost", "price", "latent_demand", "latent_price")},
        **{f"independent_{key}": independent[key] for key in ("demand", "yield", "cost", "price", "latent_demand", "latent_price")},
    )
    selected_corr = core.sample_profits(data, selected_plan, correlated)
    q2_corr = core.sample_profits(data, q2_plan, correlated)
    selected_ind = core.sample_profits(data, selected_plan, independent)
    q2_ind = core.sample_profits(data, q2_plan, independent)
    corr_stats = pilot_common.risk_stats(selected_corr)
    q2_corr_stats = pilot_common.risk_stats(q2_corr)
    ind_stats = pilot_common.risk_stats(selected_ind)
    paired_corr = selected_corr - q2_corr
    paired_ind = selected_ind - q2_ind
    risk_utility_improvement = utility(selected_corr) - utility(q2_corr)

    demand_price_correlation = float(np.corrcoef(correlated["latent_demand"].ravel(), correlated["latent_price"].ravel())[0, 1])
    substitution_correlation = pair_correlation(correlated["latent_demand"], core.SUBSTITUTION_PAIRS)
    complement_correlation = pair_correlation(correlated["latent_demand"], core.COMPLEMENT_PAIRS)
    relation_rows = []
    for relation, pairs in (("替代代理", core.SUBSTITUTION_PAIRS), ("互补代理", core.COMPLEMENT_PAIRS)):
        for left, right in pairs:
            relation_rows.append({
                "relation": relation, "left_crop_id": left, "left_crop": data.crops[left]["name"],
                "right_crop_id": right, "right_crop": data.crops[right]["name"],
                "factor_loading": "(+0.60,-0.60)" if relation == "替代代理" else "(+0.60,+0.60)",
                "economic_scope": "情景生成结构代理，不解释为估计的交叉价格弹性",
            })

    mechanism = {
        "kind": "gaussian_copula_latent_factor_scenario_model",
        "marginal_preservation": "标准正态潜变量经Phi映射为U(0,1)，保持Q2边际区间",
        "category_common_loading": 0.25, "pair_loading": 0.60,
        "yield_climate_loading": 0.55, "demand_price_loading": -0.35,
        "price_market_loading": 0.45, "cost_market_loading": 0.50,
        "substitution_pairs": [list(pair) for pair in core.SUBSTITUTION_PAIRS],
        "complement_pairs": [list(pair) for pair in core.COMPLEMENT_PAIRS],
        "empirical_demand_price_correlation": demand_price_correlation,
        "empirical_substitution_pair_correlation": substitution_correlation,
        "empirical_complement_pair_correlation": complement_correlation,
        "positive_semidefinite_reason": "相关结构由独立潜在因子的线性组合构造，协方差矩阵天然半正定",
        "scope": "情景分析假设，不是历史数据估计",
    }
    pilot_common.write_json(artifacts / "correlation_mechanism.json", mechanism)

    core.fill_template(RUN_DIR / "materials/templates/result2.xlsx", RUN_DIR / "official/result3_supplement.xlsx", selected_plan, data)
    pd.DataFrame(candidate_rows).to_csv(tables / "candidate_evaluation.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "sample_id": range(FINAL_SCENARIOS), "q3_correlated": selected_corr, "q2_correlated": q2_corr,
        "q3_independent": selected_ind, "q2_independent": q2_ind,
        "paired_correlated": paired_corr, "paired_independent": paired_ind,
    }).to_csv(tables / "final_sample_profits.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(difference_rows).sort_values("change_mu", key=lambda x: x.abs(), ascending=False).to_csv(tables / "plan_difference.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(relation_rows).to_csv(tables / "crop_relations.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{ "candidate_id": key, **value } for key, value in solver_meta.items()]).to_csv(tables / "solver_evidence.csv", index=False, encoding="utf-8-sig")
    convergence_rows = []
    for count in (256, 512, 1024, FINAL_SCENARIOS):
        for strategy, values in (("Q3 相关风险方案", selected_corr[:count]), ("Q2 独立情景方案", q2_corr[:count])):
            convergence_rows.append({"sample_count": count, "strategy": strategy, **pilot_common.risk_stats(values)})
    pd.DataFrame(convergence_rows).to_csv(tables / "sample_convergence.csv", index=False, encoding="utf-8-sig")

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 9})
    colors = ["#0072B2", "#009E73", "#CC79A7", "#777777"]
    crop_ids = sorted(set(sum((list(pair) for pair in core.SUBSTITUTION_PAIRS[:3] + core.COMPLEMENT_PAIRS[:2]), [])))
    matrix = np.corrcoef(correlated["latent_demand"][:, :, np.array(crop_ids) - 1].reshape(-1, len(crop_ids)), rowvar=False)
    names = [data.crops[crop]["name"] for crop in crop_ids]
    fig, ax = plt.subplots(figsize=(6.2, 5.0)); image = ax.imshow(matrix, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(names)), names, rotation=35, ha="right"); ax.set_yticks(range(len(names)), names); fig.colorbar(image, ax=ax, label="需求潜变量相关系数"); fig.tight_layout(); save_figure(fig, "demand_correlation")
    fig, ax = plt.subplots(figsize=(6.2, 3.7)); ax.hist(paired_corr / 1e4, bins=35, alpha=0.78, color=colors[0], label="相关情景"); ax.hist(paired_ind / 1e4, bins=35, alpha=0.45, color=colors[1], label="独立边际对照")
    ax.axvline(0, color="black", linewidth=0.8); ax.set(xlabel="Q3 相对 Q2 的配对利润差（万元）", ylabel="样本数"); ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "paired_difference")
    diff_frame = pd.DataFrame(difference_rows); crop_change = diff_frame.groupby("crop_name").change_mu.sum().sort_values(key=lambda x: x.abs(), ascending=False).head(10)
    fig, ax = plt.subplots(figsize=(6.2, 3.7)); ax.bar(crop_change.index, crop_change.values, color=[colors[1] if value >= 0 else colors[2] for value in crop_change.values]); ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("相对 Q2 的七年累计面积变化（亩）"); ax.tick_params(axis="x", rotation=25); ax.spines[["top", "right"]].set_visible(False); fig.tight_layout(); save_figure(fig, "plan_changes")

    stop.set()
    max_gap = max(float(value["mip_gap"]) for value in solver_meta.values())
    if max_gap > 0.10:
        raise RuntimeError(f"Q3 最大 MIP gap={max_gap:.3%}，超过冻结的 10% 里程碑")
    result = {
        "question_id": "q3", "status": "complete",
        "metrics": {
            "correlated_mean_profit": {"value": corr_stats["mean"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "correlated_std_profit": {"value": corr_stats["std"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "correlated_p05_profit": {"value": corr_stats["p05"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "correlated_cvar05_profit": {"value": corr_stats["cvar05"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "q2_correlated_mean_profit": {"value": q2_corr_stats["mean"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "q2_correlated_cvar05_profit": {"value": q2_corr_stats["cvar05"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "cvar05_improvement": {"value": corr_stats["cvar05"] - q2_corr_stats["cvar05"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "risk_utility_improvement": {"value": risk_utility_improvement, "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "paired_mean_improvement": {"value": float(paired_corr.mean()), "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "paired_improvement_probability": {"value": float(np.mean(paired_corr > 0)), "unit": "", "format": {"scale": 0.01, "decimals": 2, "suffix": "%"}},
            "independent_mean_profit": {"value": ind_stats["mean"], "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}},
            "plan_l1_change": {"value": float(sum(abs(row["change_mu"]) for row in difference_rows)), "unit": "亩", "format": {"scale": 1, "decimals": 2, "suffix": "亩"}},
            "demand_price_correlation": {"value": demand_price_correlation, "unit": "", "format": {"scale": 1, "decimals": 3, "suffix": ""}},
            "substitution_pair_correlation": {"value": substitution_correlation, "unit": "", "format": {"scale": 1, "decimals": 3, "suffix": ""}},
            "complement_pair_correlation": {"value": complement_correlation, "unit": "", "format": {"scale": 1, "decimals": 3, "suffix": ""}},
            "max_mip_gap": {"value": max_gap, "unit": "", "format": {"scale": 0.01, "decimals": 2, "suffix": "%"}},
            "final_sample_count": {"value": FINAL_SCENARIOS, "unit": "个", "format": {"scale": 1, "decimals": 0, "suffix": "个"}},
        },
        "check_requests": [{"id": check, "kind": check} for check in ("hard_constraints", "held_out_evaluation", "sample_separation", "correlation_mechanism", "plan_reoptimisation", "solver_evidence", "scenario_comparison", "body_metric_binding")],
        "tables": [{"path": f"questions/q3/results/tables/{name}"} for name in ("candidate_evaluation.csv", "final_sample_profits.csv", "plan_difference.csv", "crop_relations.csv", "solver_evidence.csv", "sample_convergence.csv")],
        "figures": [{"path": f"questions/q3/figures/{name}.png"} for name in ("demand_correlation", "paired_difference", "plan_changes")],
        "attachments": [{"path": "official/result3_supplement.xlsx"}],
        "solver": {"selected_candidate": selected, "selected_label": selected_label, "candidates": solver_meta, "risk_weight": RISK_WEIGHT, "tail_probability": TAIL_PROBABILITY},
        "warnings": ["相关、替代与互补参数为情景代理假设，不是历史估计", "最优性结论限定于求解前冻结的支持集"],
        "runtime": {"elapsed_seconds": pilot_common.elapsed(started), **memory},
    }
    pilot_common.write_json(artifacts / "selected_plan.json", {"candidate_id": selected, "academic_label": selected_label, "assignments": selected_plan, "candidate_evaluation": candidate_rows})
    pilot_common.write_json(artifacts / "sample_split.json", {"training": {"seeds": list(TRAIN_SEEDS), "scenarios_per_seed": TRAIN_SCENARIOS}, "candidate_evaluation": {"seed": CANDIDATE_SEED, "scenarios": CANDIDATE_SCENARIOS}, "final_correlated": {"seed": FINAL_CORRELATED_SEED, "scenarios": FINAL_SCENARIOS}, "final_independent": {"seed": FINAL_INDEPENDENT_SEED, "scenarios": FINAL_SCENARIOS}, "sets_disjoint_by_seed": True})
    pilot_common.write_json(result_dir / "result.json", result)
    pilot_common.write_json(RUN_DIR / "metrics/q3_runtime.json", result["runtime"])
    print(json.dumps({"status": "Q3_RESULT_READY", "selected": selected_label, "metrics": result["metrics"], "runtime": result["runtime"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
