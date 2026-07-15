"""复核竞赛全回放的 Formal Result、完整方案与跨语言证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


VALIDATOR_PATH = "validators/competition_replay_v21/validate.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return value


def artifacts_by_role(manifest: Mapping[str, Any], run_root: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in manifest.get("artifacts", []):
        if not isinstance(item, Mapping):
            raise ValueError("Input Manifest artifact 非法")
        path = (run_root / str(item["path"])).resolve()
        if not path.is_relative_to(run_root) or not path.is_file():
            raise ValueError(f"Input Manifest 引用非法：{item['path']}")
        if sha256(path) != item["sha256"]:
            raise ValueError(f"Input Manifest SHA-256 不匹配：{item['path']}")
        grouped.setdefault(str(item["role"]), []).append(load_json(path))
    return grouped


def one(values: list[dict[str, Any]], predicate, label: str) -> dict[str, Any]:
    matched = [value for value in values if predicate(value)]
    if len(matched) != 1:
        raise ValueError(f"{label} 应唯一匹配，实际 {len(matched)} 项")
    return matched[0]


def observation(name: str, value: float) -> dict[str, object]:
    if not math.isfinite(value):
        raise ValueError(f"观察值不是有限数：{name}")
    return {"name": name, "value": value}


def build_report(manifest_path: Path, report_path: Path) -> dict[str, object]:
    manifest = load_json(manifest_path)
    run_root = manifest_path.resolve().parents[1]
    roles = artifacts_by_role(manifest, run_root)

    problem = one(roles["problem_data"], lambda value: "material_status" in value, "Problem Manifest")
    candidates = roles["candidate_solution"]
    raw = one(candidates, lambda value: value.get("scenario_id") == "q1_waste", "Sandbox raw result")
    complete = one(candidates, lambda value: isinstance(value.get("scenarios"), list), "完整四场景结果")
    decision = one(candidates, lambda value: value.get("artifact_type") == "decision_variables", "Formal decision")

    parameters = roles["model_parameters"]
    level_a = one(parameters, lambda value: value.get("level") == "A", "MATLAB Level A")
    level_b = one(parameters, lambda value: value.get("level") == "B", "MATLAB Level B")
    validity_contract = one(
        parameters,
        lambda value: value.get("artifact_type") == "model_validity_contract",
        "模型有效性合同",
    )

    logs = roles["solver_log"]
    execution = one(logs, lambda value: value.get("artifact_type") == "sandboxie_run_execution_record", "执行记录")
    environment = one(logs, lambda value: value.get("artifact_type") == "environment_manifest", "环境清单")
    independence = one(
        logs,
        lambda value: value.get("artifact_type") == "validator_independence_manifest",
        "Validator 独立性清单",
    )

    objective_check = one(
        level_a["checks"],
        lambda value: value.get("name") == "scenario.q1_waste.objective",
        "Q1 目标复算",
    )
    reported_objective = float(raw["objective"])
    recomputed_objective = float(objective_check["matlab_value"])
    absolute_error = abs(reported_objective - recomputed_objective)

    residuals = [float(raw.get("max_constraint_violation", math.inf))]
    residuals.extend(
        float(item["matlab_value"])
        for item in level_a["checks"]
        if str(item.get("name", "")).endswith("max_constraint_violation")
    )
    max_constraint_residual = max(residuals)

    q1 = one(complete["scenarios"], lambda value: value.get("scenario_id") == "q1_waste", "完整结果 Q1")
    objective_consistent = (
        abs(float(decision["payload"]["x"]) - reported_objective) <= 1e-6
        and abs(float(q1["objective_reported"]) - reported_objective) <= 1e-6
        and int(raw["assignment_count"]) == len(q1["assignments"])
    )

    max_domain_violation = 0.0
    for scenario in complete["scenarios"]:
        for assignment in scenario["assignments"]:
            area = float(assignment["area_mu"])
            year = int(assignment["year"])
            crop = int(assignment["crop_id"])
            max_domain_violation = max(
                max_domain_violation,
                max(0.0, -area),
                max(0.0, 2024 - year, year - 2030),
                max(0.0, 1 - crop, crop - 41),
            )

    environment_payload = environment["payload"]
    solver_ok = all(
        (
            problem.get("material_status") == "ready",
            raw.get("solver_status") in {"feasible", "optimal"},
            raw.get("constraint_feasible") is True,
            execution.get("exit_code") == 0,
            execution.get("output_set_exact") is True,
            environment_payload.get("formal_result_eligible") is True,
            level_a.get("status") == "passed",
            level_b.get("status") == "passed",
            level_a.get("full_model_solved") is False,
            level_b.get("full_model_solved") is False,
            validity_contract.get("contract_status") == "planned",
            independence.get("f5_status") == "pass",
        )
    )
    solver_exit_code = 0.0 if solver_ok else 1.0

    checks = [
        {
            "check_id": "objective_recomputation",
            "observations": [
                observation("reported_objective", reported_objective),
                observation("recomputed_objective", recomputed_objective),
                observation("absolute_error", absolute_error),
            ],
        },
        {
            "check_id": "constraint_residual",
            "observations": [observation("max_constraint_residual", max_constraint_residual)],
        },
        {
            "check_id": "decision_output_consistency",
            "observations": [observation("decision_output_match", 1.0 if objective_consistent else 0.0)],
        },
        {
            "check_id": "variable_domain",
            "observations": [observation("max_domain_violation", max_domain_violation)],
        },
        {
            "check_id": "solver_status",
            "observations": [observation("solver_exit_code", solver_exit_code)],
        },
    ]
    validator = Path(__file__).resolve()
    report = {
        "validator_path": VALIDATOR_PATH,
        "validator_sha256": sha256(validator),
        "input_manifest_sha256": sha256(manifest_path),
        "checks": checks,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    build_report(Path(args.input_manifest), Path(args.report))
    print("competition replay v2.1 validator completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
