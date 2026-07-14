"""用于测试父进程执行链的最小可执行 Gate 3 Validator。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping


VALIDATOR_PATH = "validators/gate3_evidence_fixture/validate.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return value


def _artifact_by_role(manifest: Mapping[str, Any], run_root: Path) -> dict[str, Path]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Input Manifest 缺少 artifacts")
    result: dict[str, Path] = {}
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise ValueError("Input Manifest artifact 非法")
        role = str(item["role"])
        if role in result:
            raise ValueError(f"测试 Validator 每个角色只接受一个文件：{role}")
        path = (run_root / str(item["path"])).resolve()
        if not path.is_relative_to(run_root) or not path.is_file():
            raise ValueError(f"Input Manifest 引用非法：{item['path']}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"Input Manifest SHA-256 不匹配：{item['path']}")
        result[role] = path
    return result


def _number(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _candidate_value(candidate: Mapping[str, Any]) -> float:
    if isinstance(candidate.get("x"), (int, float)):
        return float(candidate["x"])
    metrics = candidate.get("metrics")
    if isinstance(metrics, list) and metrics and isinstance(metrics[0], Mapping):
        return _number(metrics[0].get("value"), 0.0)
    return 0.0


def _solver_exit_code(solver_log: Mapping[str, Any]) -> int:
    if isinstance(solver_log.get("exit_code"), int):
        return int(solver_log["exit_code"])
    executions = solver_log.get("executions")
    if isinstance(executions, list) and executions and isinstance(executions[0], Mapping):
        value = executions[0].get("exit_code")
        if isinstance(value, int):
            return value
    return 0


def _observation(name: str, value: float) -> dict[str, object]:
    return {"name": name, "value": value}


def _build_report(
    manifest_path: Path,
    report_path: Path,
) -> dict[str, object]:
    manifest = _load_object(manifest_path)
    run_root = manifest_path.resolve().parents[1]
    paths = _artifact_by_role(manifest, run_root)
    problem = _load_object(paths["problem_data"])
    candidate = _load_object(paths["candidate_solution"])
    parameters = _load_object(paths["model_parameters"])
    solver_log = _load_object(paths["solver_log"])

    fixture_mode = parameters.get("fixture_mode")
    if fixture_mode == "timeout":
        time.sleep(2.0)
    if fixture_mode == "nonzero":
        print("fixture requested nonzero exit", file=sys.stderr)
        raise SystemExit(7)

    x = _candidate_value(candidate)
    coefficient = _number(parameters.get("objective_coefficient"), 1.0)
    tolerance = _number(parameters.get("tolerance"), 1e-6)
    recomputed_objective = coefficient * x * x
    reported_objective = _number(candidate.get("reported_objective"), recomputed_objective)
    lower_bound = _number(problem.get("lower_bound"), float("-inf"))
    upper_bound = _number(problem.get("upper_bound"), float("inf"))
    domain_violation = max(lower_bound - x, x - upper_bound, 0.0)
    solver_exit_code = _solver_exit_code(solver_log)
    replay_value = _number(solver_log.get("replay_value"), x)
    sample_expected = problem.get("sample_manifest_id")
    sample_actual = candidate.get("sample_manifest_id")
    sample_match = 1.0 if sample_expected is None or sample_expected == sample_actual else 0.0

    checks = [
        {
            "check_id": "objective_recomputation",
            "observations": [
                _observation("reported_objective", reported_objective),
                _observation("recomputed_objective", recomputed_objective),
                _observation("absolute_error", abs(reported_objective - recomputed_objective)),
            ],
        },
        {
            "check_id": "constraint_residual",
            "observations": [_observation("max_constraint_residual", domain_violation)],
        },
        {
            "check_id": "decision_output_consistency",
            "observations": [
                _observation(
                    "decision_output_match",
                    1.0 if abs(reported_objective - recomputed_objective) <= tolerance else 0.0,
                )
            ],
        },
        {
            "check_id": "variable_domain",
            "observations": [_observation("max_domain_violation", domain_violation)],
        },
        {
            "check_id": "solver_status",
            "observations": [_observation("solver_exit_code", float(solver_exit_code))],
        },
        {
            "check_id": "random_seed_replay",
            "observations": [_observation("replay_max_abs_error", abs(replay_value - x))],
        },
        {
            "check_id": "sample_manifest_consistency",
            "observations": [_observation("sample_manifest_match", sample_match)],
        },
    ]
    validator_path = Path(__file__).resolve()
    report = {
        "validator_path": VALIDATOR_PATH,
        "validator_sha256": _sha256(validator_path),
        "input_manifest_sha256": _sha256(manifest_path),
        "checks": checks,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    _build_report(Path(args.input_manifest), Path(args.report))
    print("gate3 fixture validator executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
