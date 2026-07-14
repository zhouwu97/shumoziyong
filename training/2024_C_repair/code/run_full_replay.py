"""连续执行 Gate 3：四个场景求解、独立复算、约束检查和随机复现证据。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from load_data import load_data
from recompute_objective import evaluate_samples
from scenario_generation import Q2_SEED, Q3_COMPARISON_SEED, Q3_SEED, generate_q2, generate_q3
from solve_q1 import solve_q1
from solve_q2 import solve_q2
from solve_q3 import solve_q3


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def risk_summary(values: pd.DataFrame) -> dict[str, float]:
    profits = values["objective"]
    threshold = float(profits.quantile(0.10))
    cvar = float(profits.loc[profits <= threshold].mean())
    return {
        "scenario_count": int(len(values)),
        "mean_objective": float(profits.mean()),
        "std_objective": float(profits.std(ddof=0)),
        "p05_objective": float(profits.quantile(0.05)),
        "p10_objective": threshold,
        "cvar10_objective": cvar,
        "minimum_objective": float(profits.min()),
        "maximum_objective": float(profits.max()),
    }


def validate_reproduction(saved: pd.DataFrame, regenerated: pd.DataFrame) -> dict[str, object]:
    saved = saved.sort_index(axis=1).sort_values(list(saved.columns)).reset_index(drop=True)
    regenerated = regenerated.sort_index(axis=1).sort_values(list(regenerated.columns)).reset_index(drop=True)
    numeric = saved.select_dtypes(include="number").columns
    non_numeric = [column for column in saved.columns if column not in numeric]
    same_shape = saved.shape == regenerated.shape
    same_text = all(saved[column].equals(regenerated[column]) for column in non_numeric)
    max_error = 0.0
    if same_shape and len(numeric):
        max_error = float(np.abs(saved[numeric].to_numpy() - regenerated[numeric].to_numpy()).max())
    return {"same_shape": same_shape, "same_text": same_text, "max_absolute_error": max_error, "passed": same_shape and same_text and max_error <= 1e-12}


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    data = load_data()
    q1 = solve_q1(data, RESULTS)
    q2 = solve_q2(data, RESULTS / "q2")
    q3 = solve_q3(data, RESULTS / "q3")

    # Q2、Q3 各自在训练样本上复算风险；Q3 再以独立相关情景公平比较 Q2 与 Q3 策略。
    q2_values = evaluate_samples(q2["solution"], data, q2["samples"], alpha=0.0)
    q2_values.to_csv(RESULTS / "q2" / "simulation_values.csv", index=False)
    write_json(RESULTS / "q2" / "simulation_summary.json", risk_summary(q2_values))
    q3_values = evaluate_samples(q3["solution"], data, q3["samples"], alpha=0.0)
    q3_values.to_csv(RESULTS / "q3" / "simulation_values.csv", index=False)
    write_json(RESULTS / "q3" / "simulation_summary.json", risk_summary(q3_values))

    comparison = generate_q3(data, count=256, comparison=True)
    comparison.to_csv(RESULTS / "q3" / "independent_comparison_samples.csv", index=False)
    q2_comparison = evaluate_samples(q2["solution"], data, comparison, alpha=0.0)
    q3_comparison = evaluate_samples(q3["solution"], data, comparison, alpha=0.0)
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

    cases = {**q1, "q2": q2, "q3": q3}
    validations = {case_id: outcome["validation"] for case_id, outcome in cases.items()}
    aggregate_constraints = {
        case_id: outcome["constraints"] for case_id, outcome in cases.items()
    }
    max_error = max(value["absolute_error"] for value in validations.values())
    write_json(
        RESULTS / "objective_validation.json",
        {
            "passed_scenarios": sum(value["passed"] for value in validations.values()),
            "total_scenarios": 4,
            "max_absolute_error": max_error,
            "tolerance": 1e-6,
            "cases": validations,
        },
    )
    write_json(RESULTS / "constraint_validation.json", aggregate_constraints)

    q2_saved = pd.read_csv(RESULTS / "q2" / "scenario_samples.csv")
    q3_saved = pd.read_csv(RESULTS / "q3" / "scenario_samples.csv")
    reproduction = {
        "q2": {"seed": Q2_SEED, **validate_reproduction(q2_saved, generate_q2(data))},
        "q3": {"seed": Q3_SEED, **validate_reproduction(q3_saved, generate_q3(data))},
    }
    write_json(RESULTS / "reproduction_validation.json", reproduction)


if __name__ == "__main__":
    main()
