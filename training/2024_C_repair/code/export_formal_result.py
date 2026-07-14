"""仅将已验证的原始决策变量映射为冻结 Validator 所需的四场景合同。"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
CASE_MAP = {
    "q1_waste": "q1_unsold",
    "q1_discount": "q1_discount50",
    "q2_frozen": "q2",
    "q3_frozen": "q3",
}


def main() -> None:
    objective_validation = json.loads((RESULTS / "objective_validation.json").read_text(encoding="utf-8"))
    scenarios: list[dict[str, object]] = []
    for formal_name, result_name in CASE_MAP.items():
        raw = json.loads((RESULTS / result_name / "raw_solution.json").read_text(encoding="utf-8"))
        # 保留完整精度、所有面积变量及原字段名；不重算、不舍入、不改变求解口径。
        assignments = [
            {
                "plot_id": item["plot_id"],
                "year": item["year"],
                "season": item["season"],
                "crop_id": item["crop_id"],
                "area_mu": item["area"],
            }
            for item in raw["decision_variables"]
        ]
        scenarios.append({
            "scenario_id": formal_name,
            "assignments": assignments,
            "objective_reported": objective_validation["cases"][result_name]["recomputed_objective"],
        })
    # 冻结 Validator 按场景列表读取；每项保留原始双精度 assignment 和已复算目标。
    payload = {"scenarios": scenarios}
    (RESULTS / "formal_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
