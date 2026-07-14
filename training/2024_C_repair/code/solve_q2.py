"""按保存的 Q2 情景样本构造保守参数并求解。"""

from __future__ import annotations

from pathlib import Path

from build_model import build_model, solve_model
from export_results import export_case
from load_data import ProblemData
from scenario_generation import Q2_SEED, generate_q2, robust_parameters, save_scenarios


def solve_q2(data: ProblemData, output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    samples = generate_q2(data)
    save_scenarios(samples, output_root, Q2_SEED, "q2_training")
    parameters = robust_parameters(samples)
    model = build_model(data, parameters, alpha=0.0)
    result = solve_model(model, time_limit=30.0)
    if result.x is None:
        raise RuntimeError(f"q2 未生成可验证解：{result.message}")
    outcome = export_case("q2", model, result, data, parameters, 0.0, output_root)
    outcome["samples"] = samples
    return outcome
