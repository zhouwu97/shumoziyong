"""在已完成的随机求解结果上补做独立相关情景比较，不重复求解。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from load_data import load_data
from recompute_objective import evaluate_samples
from run_full_replay import risk_summary, validate_reproduction
from scenario_generation import Q2_SEED, Q3_COMPARISON_SEED, Q3_SEED, generate_q2, generate_q3


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
COMPARISON_COUNT = 64


def read_solution(path: Path) -> pd.DataFrame:
    return pd.DataFrame(json.loads(path.read_text(encoding="utf-8"))["decision_variables"])


def main() -> None:
    data = load_data()
    q2_solution = read_solution(RESULTS / "q2_stochastic" / "raw_solution.json")
    q3_solution = read_solution(RESULTS / "q3_stochastic" / "raw_solution.json")
    samples = generate_q3(data, count=COMPARISON_COUNT, comparison=True)
    samples.to_csv(RESULTS / "q3_stochastic" / "independent_comparison_samples.csv", index=False, float_format="%.17g")
    q2_values = evaluate_samples(q2_solution, data, samples, alpha=0.0)
    q3_values = evaluate_samples(q3_solution, data, samples, alpha=0.0)
    q2_values.to_csv(RESULTS / "q3_stochastic" / "q2_on_independent_samples.csv", index=False)
    q3_values.to_csv(RESULTS / "q3_stochastic" / "q3_on_independent_samples.csv", index=False)
    q2_risk, q3_risk = risk_summary(q2_values), risk_summary(q3_values)
    (RESULTS / "q3_stochastic" / "q3_comparison.json").write_text(
        json.dumps(
            {
                "comparison_seed": Q3_COMPARISON_SEED,
                "scenario_count": COMPARISON_COUNT,
                "q2": q2_risk,
                "q3": q3_risk,
                "mean_difference_q3_minus_q2": q3_risk["mean_objective"] - q2_risk["mean_objective"],
                "cvar10_difference_q3_minus_q2": q3_risk["cvar10_objective"] - q2_risk["cvar10_objective"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    q2_saved = pd.read_csv(RESULTS / "q2_stochastic" / "scenario_samples.csv", float_precision="round_trip")
    q3_saved = pd.read_csv(RESULTS / "q3_stochastic" / "scenario_samples.csv", float_precision="round_trip")
    (RESULTS / "reproduction_validation.json").write_text(
        json.dumps(
            {
                "q2_stochastic": {"seed": Q2_SEED, **validate_reproduction(q2_saved, generate_q2(data))},
                "q3_stochastic": {"seed": Q3_SEED, **validate_reproduction(q3_saved, generate_q3(data))},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
