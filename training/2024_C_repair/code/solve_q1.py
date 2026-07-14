"""求解 Q1 的两个销售处置情景。"""

from __future__ import annotations

from pathlib import Path

from build_model import build_model, solve_model
from export_results import export_case
from load_data import ProblemData
from scenario_generation import deterministic_parameters


def solve_q1(data: ProblemData, output_root: Path) -> dict[str, dict[str, object]]:
    parameters = deterministic_parameters(data)
    outcomes = {}
    for case_id, alpha in (("q1_unsold", 0.0), ("q1_discount50", 0.5)):
        model = build_model(data, parameters, alpha)
        result = solve_model(model)
        if result.x is None:
            raise RuntimeError(f"{case_id} 未生成可验证解：{result.message}")
        outcomes[case_id] = export_case(case_id, model, result, data, parameters, alpha, output_root / case_id)
    return outcomes
