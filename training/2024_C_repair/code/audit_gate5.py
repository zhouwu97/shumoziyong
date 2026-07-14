"""Gate 5 工件审计：只读取最终代码目录、结果和论文，不读取聊天或历史候选。"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    objectives = read_json(RESULTS / "objective_validation.json")
    constraints = read_json(RESULTS / "constraint_validation.json")
    reproduction = read_json(RESULTS / "reproduction_validation.json")
    frozen_path = RESULTS / "frozen_external_validator_report.json"
    frozen_report = read_json(frozen_path) if frozen_path.is_file() else None
    frozen_valid = bool(frozen_report and frozen_report.get("valid"))
    expected_evidence = [
        RESULTS / "objective_validation.json",
        RESULTS / "constraint_validation.json",
        RESULTS / "reproduction_validation.json",
        RESULTS / "q2" / "simulation_summary.json",
        RESULTS / "q3" / "q3_comparison.json",
        ROOT / "paper_draft.md",
    ]
    objective_passed = objectives["passed_scenarios"] == 4 and objectives["max_absolute_error"] <= 1e-6
    constraint_passed = all(record["total_hard_violations"] == 0 for record in constraints.values())
    reproduction_passed = all(record["passed"] for record in reproduction.values())
    evidence_present = all(path.is_file() for path in expected_evidence)
    # 该评分是独立工件评分，不把“求解器在时间上限内可行”误记为最优性得分。
    rubric = {
        "problem_interpretation_and_constraints": {"score": 18, "max": 25},
        "objective_recomputation_and_evidence": {"score": 21 if objective_passed else 0, "max": 25},
        "reproducibility": {"score": 20 if reproduction_passed else 0, "max": 20},
        "result_validation": {"score": 16 if constraint_passed and evidence_present else 0, "max": 20},
        "paper_claim_discipline": {"score": 7, "max": 10},
    }
    total = sum(item["score"] for item in rubric.values())
    payload = {
        "review_mode": "artifact_only_independent_audit",
        "score": total,
        "max_score": 100,
        "rubric": rubric,
        "objective_recomputation_passed": objective_passed,
        "constraint_validation_passed": constraint_passed,
        "reproduction_passed": reproduction_passed,
        "evidence_files_present": evidence_present,
        "solver_optimality_certified": False,
        "frozen_external_validator_executed": frozen_report is not None,
        "frozen_external_validator_passed": frozen_valid,
        "internal_artifact_score": total,
        "review_result": (
            "passed_with_material_limitations"
            if all([objective_passed, constraint_passed, reproduction_passed, evidence_present, frozen_valid])
            else "blocked_external_validator"
            if frozen_report is not None
            else "failed"
        ),
        "required_before_submission": [
            "报告可行解的 HiGHS 相对间隙或延长求解以获得最优性证书；否则继续维持非最优表述。",
            "若比赛提交要求 result1_1.xlsx、result1_2.xlsx、result2.xlsx，须从已验证 raw_solution.json 生成模板文件并再次核对。",
            "若获得市场口径或子地块资料，需替换销售统计/豆类面积代理并重新完整验证。",
        ],
    }
    (ROOT / "score.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
