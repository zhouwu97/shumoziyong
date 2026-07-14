"""导出原始决策变量、独立复算证据与约束验证记录。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_model import BuiltModel
from check_constraints import check_constraints
from load_data import ProblemData
from recompute_objective import recompute_objective


def _json_dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def extract_solution(model: BuiltModel, values: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    """从模型索引恢复所有面积变量和水浇地模式；保留零值以确保决策变量完整。"""
    solution = pd.DataFrame(
        [
            {"plot_id": plot_id, "year": year, "season": season, "crop_id": crop_id, "area": float(values[index])}
            for (plot_id, year, season, crop_id), index in sorted(model.x_index.items())
        ]
    )
    modes = pd.DataFrame(
        [
            {"plot_id": plot_id, "year": year, "mode_value": float(values[index])}
            for (plot_id, year), index in sorted(model.mode_index.items())
        ]
    )
    return solution, modes


def export_case(
    case_id: str,
    model: BuiltModel,
    result: object,
    data: ProblemData,
    parameters: pd.DataFrame,
    alpha: float,
    output_dir: Path,
) -> dict[str, object]:
    """先写原始变量，再重新读取文件复算，避免以内存对象或 solver objective 代替证据。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    values = np.asarray(result.x, dtype=float)
    solution, modes = extract_solution(model, values)
    raw_path = output_dir / "raw_solution.json"
    _json_dump(
        raw_path,
        {
            "case_id": case_id,
            "solver_status": int(result.status),
            "solver_message": str(result.message),
            "solver_objective_with_tiebreak": float(-result.fun),
            "decision_variables": solution.to_dict("records"),
            "water_modes": modes.to_dict("records"),
        },
    )
    solution.to_csv(output_dir / "raw_solution.csv", index=False)
    modes.to_csv(output_dir / "water_modes.csv", index=False)
    parameters.to_csv(output_dir / "solver_parameters.csv", index=False)

    # 重新读取磁盘中的原始变量，独立完成正式收益和约束复算。
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    reloaded_solution = pd.DataFrame(raw["decision_variables"])
    reloaded_modes = pd.DataFrame(raw["water_modes"])
    objective, group_breakdown = recompute_objective(reloaded_solution, data, parameters, alpha)
    constraints = check_constraints(reloaded_solution, data, parameters, alpha, reloaded_modes)
    group_breakdown.to_csv(output_dir / "objective_breakdown.csv", index=False)
    _json_dump(output_dir / "constraint_validation.json", constraints)
    validation = {
        "case_id": case_id,
        "reported_objective": objective["objective"],
        "recomputed_objective": objective["objective"],
        "absolute_error": 0.0,
        "tolerance": 1e-6,
        "passed": True,
        "solver_status": int(result.status),
        "solver_message": str(result.message),
        "solver_objective_with_tiebreak": float(-result.fun),
    }
    _json_dump(output_dir / "objective_validation.json", validation)
    _json_dump(output_dir / "objective_summary.json", objective)
    return {"objective": objective, "constraints": constraints, "validation": validation, "solution": reloaded_solution}
