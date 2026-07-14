"""按相关 Q3 情景构造保守参数并求解。"""

from __future__ import annotations

from pathlib import Path

from build_model import build_model, solve_model
from export_results import export_case
from load_data import ProblemData
from scenario_generation import Q3_SEED, generate_q3, robust_parameters, save_scenarios


def solve_q3(data: ProblemData, output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    samples = generate_q3(data)
    save_scenarios(samples, output_root, Q3_SEED, "q3_training")
    parameters = robust_parameters(samples)
    model = build_model(data, parameters, alpha=0.0)
    result = solve_model(model, time_limit=30.0)
    if result.x is None:
        raise RuntimeError(f"q3 未生成可验证解：{result.message}")
    outcome = export_case("q3", model, result, data, parameters, 0.0, output_root)
    outcome["samples"] = samples
    return outcome
