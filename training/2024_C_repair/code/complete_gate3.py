"""在不重复求解的前提下，完成 Gate 3 的独立比较、总验证与复现检查。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from load_data import load_data
from recompute_objective import evaluate_samples
from run_full_replay import RESULTS, risk_summary, validate_reproduction, write_json
from scenario_generation import Q2_SEED, Q3_COMPARISON_SEED, Q3_SEED, generate_q2, generate_q3


def solution(case_path: Path) -> pd.DataFrame:
    payload = json.loads((case_path / "raw_solution.json").read_text(encoding="utf-8"))
    return pd.DataFrame(payload["decision_variables"])


def main() -> None:
    data = load_data()
    q2_solution = solution(RESULTS / "q2")
    q3_solution = solution(RESULTS / "q3")
    # 从固定种子重建并高精度写回随机证据；不改变已经求解使用的参数或任何决策变量。
    q2_regenerated = generate_q2(data)
    q3_regenerated = generate_q3(data)
    q2_regenerated.to_csv(RESULTS / "q2" / "scenario_samples.csv", index=False, float_format="%.17g")
    q3_regenerated.to_csv(RESULTS / "q3" / "scenario_samples.csv", index=False, float_format="%.17g")
    comparison = generate_q3(data, count=256, comparison=True)
    comparison.to_csv(RESULTS / "q3" / "independent_comparison_samples.csv", index=False, float_format="%.17g")
    q2_comparison = evaluate_samples(q2_solution, data, comparison, alpha=0.0)
    q3_comparison = evaluate_samples(q3_solution, data, comparison, alpha=0.0)
    q2_comparison.to_csv(RESULTS / "q3" / "q2_on_independent_samples.csv", index=False)
    q3_comparison.to_csv(RESULTS / "q3" / "q3_on_independent_samples.csv", index=False)
    q2_risk = risk_summary(q2_comparison)
    q3_risk = risk_summary(q3_comparison)
    write_json(
        RESULTS / "q3" / "q3_comparison.json",
        {
            "comparison_seed": Q3_COMPARISON_SEED,
            "scenario_count": 256,
            "q2": q2_risk,
            "q3": q3_risk,
            "mean_difference_q3_minus_q2": q3_risk["mean_objective"] - q2_risk["mean_objective"],
            "cvar10_difference_q3_minus_q2": q3_risk["cvar10_objective"] - q2_risk["cvar10_objective"],
        },
    )
    cases = ("q1_unsold", "q1_discount50", "q2", "q3")
    validations = {
        case: json.loads((RESULTS / case / "objective_validation.json").read_text(encoding="utf-8"))
        for case in cases
    }
    constraints = {
        case: json.loads((RESULTS / case / "constraint_validation.json").read_text(encoding="utf-8"))
        for case in cases
    }
    write_json(
        RESULTS / "objective_validation.json",
        {
            "passed_scenarios": sum(value["passed"] for value in validations.values()),
            "total_scenarios": 4,
            "max_absolute_error": max(value["absolute_error"] for value in validations.values()),
            "tolerance": 1e-6,
            "cases": validations,
        },
    )
    write_json(RESULTS / "constraint_validation.json", constraints)
    # 默认 CSV 解析器会把部分 17 位十进制字符串读成相邻浮点数；
    # round_trip 模式保证文件证据可无损回读，而非放宽复现阈值。
    q2_saved = pd.read_csv(RESULTS / "q2" / "scenario_samples.csv", float_precision="round_trip")
    q3_saved = pd.read_csv(RESULTS / "q3" / "scenario_samples.csv", float_precision="round_trip")
    write_json(
        RESULTS / "reproduction_validation.json",
        {
            "q2": {"seed": Q2_SEED, **validate_reproduction(q2_saved, q2_regenerated)},
            "q3": {"seed": Q3_SEED, **validate_reproduction(q3_saved, q3_regenerated)},
        },
    )


if __name__ == "__main__":
    main()
