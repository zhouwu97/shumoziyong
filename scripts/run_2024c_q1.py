"""运行 2024-C Q1 两种情形并生成可独立复算的正式产物。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domains.problem_2024_c.data_loader import load_problem_data, resolve_material_root
from domains.problem_2024_c.official_output_schema import (
    Assignment,
    export_official_workbook,
    import_official_workbook,
)
from domains.problem_2024_c.solver import (
    SolverResult,
    SolverSettings,
    calculate_profit,
    deterministic_parameters,
    solve_q1,
)
from validators.competition_full_replay.problem_2024_c import validate_q1_workbook
from validators.problem_2024c_q1.validate import validate_q1_result


SCENARIOS = {
    "q1_waste": "result1_1.xlsx",
    "q1_discount": "result1_2.xlsx",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _scenario_result(
    result: SolverResult,
    workbook: Path,
    exported_assignments: tuple[Assignment, ...],
    exported_objective: float,
) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario_id,
        "objective_reported": exported_objective,
        "assignments": [asdict(item) for item in exported_assignments],
        "output_workbook_status": "generated",
        "output_workbook_path": _relative_or_absolute(workbook),
        "output_workbook_sha256": _sha256(workbook),
    }


def run_q1(
    material_root: Path,
    output_dir: Path,
    settings: SolverSettings,
    material_manifest: Path | None = None,
) -> dict[str, Any]:
    """生成两个官方工作簿、Formal Result 和完整求解/验证日志。"""

    started_at = _utc_now()
    material_manifest = material_manifest or (
        ROOT / "formal_result" / "cases" / "2024_C" / "material_manifest.json"
    )
    attachment_1 = material_root / "2024_C" / "attachments" / "附件1.xlsx"
    attachment_2 = material_root / "2024_C" / "attachments" / "附件2.xlsx"
    data = load_problem_data(material_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    solver_results = solve_q1(data, settings)
    parameters = deterministic_parameters(data)
    formal_scenarios: list[dict[str, Any]] = []
    workbook_reports: dict[str, dict[str, object]] = {}
    exported_objectives: dict[str, float] = {}
    for result in solver_results:
        workbook_name = SCENARIOS[result.scenario_id]
        workbook = output_dir / workbook_name
        template = material_root / "2024_C" / "templates" / workbook_name
        export_official_workbook(template, workbook, data, result.assignments)
        exported_assignments = tuple(import_official_workbook(workbook, data))
        surplus_fraction = 0.0 if result.scenario_id == "q1_waste" else 0.5
        exported_objective = calculate_profit(
            exported_assignments,
            data,
            parameters,
            surplus_fraction,
        )
        report = validate_q1_workbook(
            workbook,
            data,
            result.scenario_id,
            exported_objective,
        )
        if not report["passed"]:
            constraints = cast(dict[str, Any], report["constraints"])
            raise RuntimeError(
                f"{result.scenario_id} 官方工作簿独立验证失败: "
                f"objective_error={report['objective_absolute_error_yuan']}, "
                f"violations={constraints['violation_counts']}"
            )
        workbook_reports[result.scenario_id] = report
        exported_objectives[result.scenario_id] = exported_objective
        formal_scenarios.append(
            _scenario_result(
                result,
                workbook,
                exported_assignments,
                exported_objective,
            )
        )

    formal_result = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_formal_result",
        "problem_id": "2024-C",
        "material_manifest_sha256": _sha256(material_manifest),
        "scenarios": formal_scenarios,
    }
    mathematical_report = validate_q1_result(
        formal_result,
        attachment_1,
        attachment_2,
        material_manifest,
    )
    if not mathematical_report["valid"]:
        raise RuntimeError("Q1 Formal Result 独立数学验证失败")
    if mathematical_report["production_ready"]:
        raise RuntimeError("当前合同禁止 Q1 Validator 宣称生产就绪")

    formal_result_path = output_dir / "q1_formal_result.json"
    formal_result_path.write_text(
        json.dumps(formal_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    run_log = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_solver_run_log",
        "problem_id": "2024-C",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "material_manifest": _relative_or_absolute(material_manifest),
        "material_manifest_sha256": _sha256(material_manifest),
        "solver": "scipy.optimize.milp/HiGHS",
        "settings": asdict(settings),
        "scenarios": [
            {
                "scenario_id": result.scenario_id,
                "solver_status": result.solver_status,
                "solver_message": result.solver_message,
                "mip_gap": result.mip_gap,
                "optimality_proven": result.optimality_proven,
                "fragmentation_count": result.fragmentation_count,
                "assignment_count": len(result.assignments),
                "solver_objective_yuan": result.objective_yuan,
                "exported_objective_yuan": exported_objectives[result.scenario_id],
                "export_rounding_delta_yuan": (
                    exported_objectives[result.scenario_id] - result.objective_yuan
                ),
                "workbook": formal_scenarios[index]["output_workbook_path"],
                "workbook_sha256": formal_scenarios[index]["output_workbook_sha256"],
                "workbook_validation": workbook_reports[result.scenario_id],
            }
            for index, result in enumerate(solver_results)
        ],
        "mathematical_validation": mathematical_report,
        "formal_result": _relative_or_absolute(formal_result_path),
        "formal_result_sha256": _sha256(formal_result_path),
        "q1_independent_recalculation_passed": True,
        "optimality_claimed": all(item.optimality_proven for item in solver_results),
        "qualification_claimed": False,
        "production_ready": False,
        "complete_official_old_problem_closure": 0,
    }
    run_log_path = output_dir / "q1_solver_run_log.json"
    run_log_path.write_text(
        json.dumps(run_log, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "formal_result": formal_result,
        "run_log": run_log,
        "formal_result_path": formal_result_path,
        "run_log_path": run_log_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material-root", type=Path, default=resolve_material_root())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "formal_result" / "cases" / "2024_C" / "q1",
    )
    parser.add_argument("--time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--mip-relative-gap", type=float, default=1e-4)
    parser.add_argument("--random-seed", type=int, default=20240718)
    args = parser.parse_args()
    artifacts = run_q1(
        args.material_root.resolve(),
        args.output_dir.resolve(),
        SolverSettings(
            time_limit_seconds=args.time_limit_seconds,
            mip_relative_gap=args.mip_relative_gap,
            random_seed=args.random_seed,
        ),
    )
    print(
        json.dumps(
            {
                "formal_result": str(artifacts["formal_result_path"]),
                "run_log": str(artifacts["run_log_path"]),
                "status": "validated_feasible_baseline",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
