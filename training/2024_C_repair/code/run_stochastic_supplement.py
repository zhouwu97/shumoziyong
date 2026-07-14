"""生成与冻结代表场景分离的 Q2/Q3 随机补充实验。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from load_data import load_data
from recompute_objective import evaluate_samples
from run_full_replay import risk_summary, validate_reproduction
from scenario_generation import Q2_SEED, Q3_COMPARISON_SEED, Q3_SEED, generate_q2, generate_q3
from solve_q2 import solve_q2
from solve_q3 import solve_q3


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    data = load_data()
    q2 = solve_q2(data, RESULTS / "q2_stochastic")
    q3 = solve_q3(data, RESULTS / "q3_stochastic")
    q2_values = evaluate_samples(q2["solution"], data, q2["samples"], alpha=0.0)
    q3_values = evaluate_samples(q3["solution"], data, q3["samples"], alpha=0.0)
    q2_values.to_csv(RESULTS / "q2_stochastic" / "simulation_values.csv", index=False)
    q3_values.to_csv(RESULTS / "q3_stochastic" / "simulation_values.csv", index=False)
    write_json(RESULTS / "q2_stochastic" / "simulation_summary.json", risk_summary(q2_values))
    write_json(RESULTS / "q3_stochastic" / "simulation_summary.json", risk_summary(q3_values))
    comparison = generate_q3(data, count=256, comparison=True)
    comparison.to_csv(RESULTS / "q3_stochastic" / "independent_comparison_samples.csv", index=False, float_format="%.17g")
    q2_comparison = evaluate_samples(q2["solution"], data, comparison, alpha=0.0)
    q3_comparison = evaluate_samples(q3["solution"], data, comparison, alpha=0.0)
    q2_comparison.to_csv(RESULTS / "q3_stochastic" / "q2_on_independent_samples.csv", index=False)
    q3_comparison.to_csv(RESULTS / "q3_stochastic" / "q3_on_independent_samples.csv", index=False)
    q2_risk = risk_summary(q2_comparison)
    q3_risk = risk_summary(q3_comparison)
    write_json(
        RESULTS / "q3_stochastic" / "q3_comparison.json",
        {
            "comparison_seed": Q3_COMPARISON_SEED,
            "scenario_count": 256,
            "q2": q2_risk,
            "q3": q3_risk,
            "mean_difference_q3_minus_q2": q3_risk["mean_objective"] - q2_risk["mean_objective"],
            "cvar10_difference_q3_minus_q2": q3_risk["cvar10_objective"] - q2_risk["cvar10_objective"],
        },
    )
    q2_saved = pd.read_csv(RESULTS / "q2_stochastic" / "scenario_samples.csv", float_precision="round_trip")
    q3_saved = pd.read_csv(RESULTS / "q3_stochastic" / "scenario_samples.csv", float_precision="round_trip")
    write_json(
        RESULTS / "reproduction_validation.json",
        {
            "q2_stochastic": {"seed": Q2_SEED, **validate_reproduction(q2_saved, generate_q2(data))},
            "q3_stochastic": {"seed": Q3_SEED, **validate_reproduction(q3_saved, generate_q3(data))},
        },
    )


if __name__ == "__main__":
    main()
