"""执行一次公开冻结合同对齐修复，并导出黑盒复核所需结果。"""

from __future__ import annotations

import json
from pathlib import Path

from build_model import build_model, solve_model
from export_results import export_case
from load_data import load_data
from scenario_generation import deterministic_parameters, frozen_benchmark_parameters


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    data = load_data()
    q1_parameters = deterministic_parameters(data)
    frozen_parameters = frozen_benchmark_parameters(data)
    cases = (
        ("q1_waste", q1_parameters, 0.0),
        ("q1_discount", q1_parameters, 0.5),
        ("q2_frozen", frozen_parameters, 0.0),
        ("q3_frozen", frozen_parameters, 0.0),
    )
    outcomes: dict[str, dict[str, object]] = {}
    for case_id, parameters, alpha in cases:
        model = build_model(data, parameters, alpha)
        # 冻结复核只要求可验证可行解；固定短时限避免把本轮变成无界求优。
        result = solve_model(model, time_limit=30.0)
        if result.x is None:
            raise RuntimeError(f"{case_id} 未生成可验证解：{result.message}")
        outcomes[case_id] = export_case(case_id, model, result, data, parameters, alpha, RESULTS / case_id)

    validations = {case_id: outcome["validation"] for case_id, outcome in outcomes.items()}
    constraints = {case_id: outcome["constraints"] for case_id, outcome in outcomes.items()}
    write_json(
        RESULTS / "objective_validation.json",
        {
            "passed_scenarios": sum(value["passed"] for value in validations.values()),
            "total_scenarios": len(validations),
            "max_absolute_error": max(value["absolute_error"] for value in validations.values()),
            "tolerance": 1e-6,
            "cases": validations,
        },
    )
    write_json(RESULTS / "constraint_validation.json", constraints)


if __name__ == "__main__":
    main()
