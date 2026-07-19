"""从官方材料准备隔离的 2024-C Production Pilot 目录。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = Path(__file__).resolve().parent
OFFICIAL = ROOT / "official_materials" / "2024_C"
PURE_SOLVER = ROOT / "runs" / "2024C_v21_full_replay_20260715" / "workspace" / "code" / "run_pipeline.py"
INDEPENDENT_VALIDATOR = ROOT / "validators" / "problem_positive_v2" / "validate.py"


def write_new(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_new(source: Path, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def question_config(qid: str, required: bool) -> dict[str, object]:
    checks = {
        "q1": ["hard_constraints", "objective_recalculation", "excel_readback", "sales_scenarios", "mip_gap_disclosure", "body_metric_binding"],
        "q2": ["hard_constraints", "excel_readback", "held_out_evaluation", "sample_separation", "risk_sensitivity", "baseline_comparison", "body_metric_binding"],
        "q3": ["hard_constraints", "held_out_evaluation", "sample_separation", "correlation_mechanism", "scenario_comparison", "body_metric_binding"],
    }[qid]
    return {
        "id": qid,
        "title": {"q1": "确定性种植规划", "q2": "不确定性与风险规划", "q3": "相关性、替代性与互补性"}[qid],
        "required": required,
        "checker": f"questions/{qid}/checker.py",
        "required_checks": checks,
        "recommended_checks": [],
    }


def prepare(run_dir: Path, phase: str) -> dict[str, object]:
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    required = {"q1"} if phase == "q1" else {"q1", "q2", "q3"}
    contest = {
        "version": "2.0",
        "contest_id": "2024-C-production-pilot-v2",
        "mode": "contest_standard",
        "question_ids": ["q1", "q2", "q3"],
        "required_materials": ["materials/problem/C题_extracted_text.txt", "materials/attachments/附件1.xlsx", "materials/attachments/附件2.xlsx"],
        "required_attachments": ["official/result1_1.xlsx", "official/result1_2.xlsx"] if phase == "q1" else ["official/result1_1.xlsx", "official/result1_2.xlsx", "official/result2.xlsx"],
    }
    (run_dir / "contest.json").write_text(json.dumps(contest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for relative in ["problem/C题.pdf", "problem/C题_extracted_text.txt", "attachments/附件1.xlsx", "attachments/附件2.xlsx", "templates/result1_1.xlsx", "templates/result1_2.xlsx", "templates/result2.xlsx"]:
        copy_new(OFFICIAL / relative, run_dir / "materials" / relative)
    copy_new(PURE_SOLVER, run_dir / "shared" / "solver_core.py")
    copy_new(INDEPENDENT_VALIDATOR, run_dir / "shared" / "independent_validator.py")
    copy_new(EXAMPLE / "pilot_common.py", run_dir / "shared" / "pilot_common.py")
    for qid in ("q1", "q2", "q3"):
        base = run_dir / "questions" / qid
        base.mkdir(parents=True, exist_ok=True)
        (base / "question.json").write_text(json.dumps(question_config(qid, qid in required), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        copy_new(EXAMPLE / f"{qid}_run.py", base / "run.py")
        copy_new(EXAMPLE / "checker.py", base / "checker.py")
        copy_new(EXAMPLE / f"{qid}_model.md", base / "model.md")
        copy_new(EXAMPLE / f"{qid}_paper.typ", base / "paper.typ")
        copy_new(EXAMPLE / f"{qid}_check.md", base / "check.md")
        (base / "results" / "tables").mkdir(parents=True, exist_ok=True)
        (base / "figures").mkdir(parents=True, exist_ok=True)
    copy_new(EXAMPLE / "main.typ", run_dir / "paper" / "main.typ")
    (run_dir / "paper" / "generated").mkdir(parents=True, exist_ok=True)
    (run_dir / "official").mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics").mkdir(parents=True, exist_ok=True)
    return {"run_dir": str(run_dir), "phase": phase, "required_questions": sorted(required), "source_kind": "official_materials_only"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--phase", choices=("q1", "full"), default="q1")
    args = parser.parse_args()
    print(json.dumps(prepare(args.run_dir, args.phase), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
