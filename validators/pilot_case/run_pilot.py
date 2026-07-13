"""运行 A092 非晋级 Pilot 并固化故障注入结果。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validators.common.validator import validate_solution  # noqa: E402
from validators.pilot_case.adapter import PilotProductionAdapter  # noqa: E402


OUTPUT_ROOT = ROOT / "examples" / "a092_phase2_pilot"
ARTIFACT_ROOT = OUTPUT_ROOT / "artifacts" / "a092"
VALIDATOR_SCHEMA = ROOT / "schemas" / "a092_validator_result.schema.json"

PROBLEM_DATA = {"profit_x": 8.0, "profit_y": 5.0}
BASELINE = {"x": 2.0, "y": 2.0}
SOLUTION = {"x": 6.0, "y": 2.0}
TOLERANCES = {
    "objective_absolute": 1e-9,
    "variable_absolute": 1e-9,
    "integrality_absolute": 1e-9,
    "constraint_absolute": 1e-9,
    "constraint_relative": 1e-9,
    "baseline_epsilon": 1e-12,
    "improvement_ratio_absolute": 1e-9,
}


def _sensitivity() -> dict[str, Any]:
    return {
        "status": "completed",
        "results": [
            {
                "parameter": "profit_x",
                "perturbation": "+5%",
                "relative_objective_change": 0.03,
                "solution_structure_changed": False,
                "main_conclusion_reversed": False,
                "classification": "stable",
            }
        ],
    }


def _optimality() -> dict[str, Any]:
    return {
        "method": "heuristic_search",
        "independent_checks_passed": True,
        "improves_baseline": True,
    }


def _validate_case(
    *,
    solution: Mapping[str, float] = SOLUTION,
    objective_reported: float = 58.0,
    improvement_ratio: float = 32.0 / 26.0,
    sensitivity: Mapping[str, Any] | None = None,
    optimality: Mapping[str, Any] | None = None,
    requested_claim: str = "best_found_in_search",
) -> dict[str, Any]:
    return validate_solution(
        PilotProductionAdapter(),
        solution=solution,
        problem_data=PROBLEM_DATA,
        objective_reported=objective_reported,
        baseline_solution=BASELINE,
        reported_improvement_ratio=improvement_ratio,
        sensitivity_evidence=sensitivity or _sensitivity(),
        optimality_evidence=optimality or _optimality(),
        requested_optimality_claim=requested_claim,
        tolerances=TOLERANCES,
    )


def run_fault_injections() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """返回有效样例和七类预注册故障的检测记录。"""

    valid = _validate_case()
    forged_sensitivity = _sensitivity()
    forged_sensitivity["results"][0].update(
        {"relative_objective_change": 0.20, "classification": "stable"}
    )
    cases = [
        ("wrong_objective", _validate_case(objective_reported=999.0), "objective_consistent"),
        ("out_of_bounds", _validate_case(solution={"x": 11.0, "y": 0.0}), "bounds_valid"),
        ("non_integer", _validate_case(solution={"x": 5.5, "y": 2.0}), "integrality_valid"),
        ("constraint_violation", _validate_case(solution={"x": 6.0, "y": 3.0}), "feasible"),
        (
            "wrong_improvement_ratio",
            _validate_case(improvement_ratio=9.99),
            "improvement_ratio_consistent",
        ),
        (
            "forged_sensitivity",
            _validate_case(sensitivity=forged_sensitivity),
            "sensitivity_checks_passed",
        ),
        (
            "heuristic_claimed_global_optimum",
            _validate_case(requested_claim="global_optimum_verified"),
            "optimality_claim_consistent",
        ),
    ]
    records = [
        {
            "fault_id": fault_id,
            "expected_failed_check": check,
            "detected": result[check] is False,
            "validator_result": result,
        }
        for fault_id, result, check in cases
    ]
    return valid, records


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_artifacts(valid_result: Mapping[str, Any]) -> None:
    _write_json(
        ARTIFACT_ROOT / "mechanism_chain.json",
        {
            "mechanism_chain": {
                "inputs": ["两类产品的单位收益", "两类设备容量"],
                "transformations": ["产量占用总产能与设备工时"],
                "intermediate_states": ["产品 x、y 的产量组合"],
                "loss_terms": ["超出总产能", "超出设备工时"],
                "outputs": ["总收益"],
            }
        },
    )
    _write_json(
        ARTIFACT_ROOT / "evaluation_definition.json",
        {
            "function": "8*x + 5*y",
            "objective_direction": "maximize",
            "units": "收益单位",
            "shared_by": ["baseline", "candidate", "validator"],
        },
    )
    _write_json(
        ARTIFACT_ROOT / "baseline_result.json",
        {
            "method": "人工可行规则",
            "decision_variables": BASELINE,
            "objective": 26.0,
            "feasible": True,
        },
    )
    _write_json(
        ARTIFACT_ROOT / "optimized_result.json",
        {
            "method": "启发式搜索",
            "decision_variables": SOLUTION,
            "objective_reported": 58.0,
        },
    )
    _write_json(ARTIFACT_ROOT / "validator_result.json", valid_result)
    _write_json(
        ARTIFACT_ROOT / "sensitivity_results.json",
        {
            "status": valid_result["sensitivity_status"],
            "checks_passed": valid_result["sensitivity_checks_passed"],
            "results": valid_result["sensitivity_results"],
        },
    )
    _write_json(
        ARTIFACT_ROOT / "optimality_claim.json",
        {
            "requested": valid_result["optimality_claim_requested"],
            "allowed": valid_result["optimality_claim_allowed"],
            "consistent": valid_result["optimality_claim_consistent"],
        },
    )
    _write_json(
        ARTIFACT_ROOT / "claim_map.json",
        {
            "claims": [
                {
                    "claim_id": "PILOT-C-001",
                    "claim": "候选方案收益为 58，且通过独立约束检查。",
                    "source_result": "artifacts/a092/validator_result.json",
                    "source_fields": ["objective_recomputed", "feasible"],
                    "validator_record": "artifacts/a092/validator_result.json",
                    "figure_or_table": None,
                    "paper_location": "pilot_report",
                    "supported": True,
                }
            ]
        },
    )


def main() -> int:
    valid_result, faults = run_fault_injections()
    schema = json.loads(VALIDATOR_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(valid_result)
    for fault in faults:
        Draft202012Validator(schema).validate(fault["validator_result"])
    report = {
        "schema_version": "1.0.0",
        "pilot_id": "A092-PILOT-20260713",
        "promotion_evidence": False,
        "excluded_from_roles": ["positive", "boundary", "negative"],
        "valid_case_passed": valid_result["valid"] is True,
        "fault_injections": faults,
        "all_faults_detected": all(item["detected"] for item in faults),
        "calibration_changes": [
            "约束满足采用绝对容差或缩放相对容差，避免严格等于零。",
            "敏感性分类由数值变化和结构变化共同派生，不能只信任文本标签。",
            "最优性等级由求解证据派生，启发式搜索最高只能声明当前搜索中最好。",
        ],
    }
    _write_artifacts(valid_result)
    _write_json(OUTPUT_ROOT / "pilot_result.json", report)
    print(json.dumps({"pilot_id": report["pilot_id"], "passed": report["all_faults_detected"]}))
    return 0 if report["valid_case_passed"] and report["all_faults_detected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
