"""把历史 2024-C 结果包装为 packaging smoke；不得作为生产试点。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .result_ledger import stable_json_bytes


SMOKE_KIND = "packaging_smoke_only"


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _paper() -> str:
    return '''#import "generated/results.typ": *
#set page(paper: "a4", margin: 2cm)
#set text(font: ("Microsoft YaHei", "SimSun"), lang: "zh", size: 10.5pt)
= 2024-C Packaging Smoke

本文仅验证历史结果能够经过 Result、Verification、Ledger、Typst、PDF 与 Package 包装链。
它不证明从官方材料重新建模和求解，也不是 Production Pilot。

#include "../questions/q1/paper.typ"
#include "../questions/q2/paper.typ"
#include "../questions/q3/paper.typ"
'''


def migrate(source_run: Path, target_run: Path) -> dict[str, object]:
    source_run = source_run.resolve()
    target_run = target_run.resolve()
    if target_run.exists() and any(target_run.iterdir()):
        raise FileExistsError(f"目标目录非空：{target_run}")
    target_run.mkdir(parents=True, exist_ok=True)
    report_path = source_run / "result_report.json"
    if not report_path.is_file():
        report_path = source_run / "workspace" / "results" / "result_summary.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if "metrics" in report:
        values = [float(item["value"]) for item in report["metrics"][:4]]
    else:
        summary = report["scenario_summary"]
        values = [float(summary[key]["objective_recomputed"]) for key in ("q1_waste", "q1_discount", "q2_frozen", "q3_frozen")]

    contest = {
        "version": "2.0",
        "contest_id": target_run.name,
        "mode": "contest_fast",
        "artifact_kind": SMOKE_KIND,
        "question_ids": ["q1", "q2", "q3"],
        "required_materials": [],
        "required_attachments": [],
    }
    (target_run / "contest.json").write_bytes(stable_json_bytes(contest))
    questions = [{"id": f"q{i}", "title": f"迁移问题{i}", "required": True, "required_checks": [], "recommended_checks": []} for i in range(1, 4)]
    metrics = {
        "q1": {"waste_profit": values[0], "discount_profit": values[1]},
        "q2": {"profit": values[2]},
        "q3": {"profit": values[3]},
    }
    for index, qid in enumerate(("q1", "q2", "q3"), 1):
        base = target_run / "questions" / qid
        (base / "results").mkdir(parents=True, exist_ok=True)
        question = questions[index - 1]
        (base / "question.json").write_bytes(stable_json_bytes(question))
        (base / "model.md").write_text(f"# {qid} 包装烟测\n\n历史结果只用于包装链，不重新建模。\n", encoding="utf-8")
        (base / "run.py").write_text('raise SystemExit("packaging_smoke_only")\n', encoding="utf-8")
        (base / "check.md").write_text("# Packaging smoke check\n\n只检查包装链。\n", encoding="utf-8")
        result_metrics = {
            key: {"value": value, "unit": "元", "format": {"scale": 10000, "decimals": 2, "suffix": "万元"}}
            for key, value in metrics[qid].items()
        }
        result = {"question_id": qid, "status": "complete", "metrics": result_metrics, "check_requests": [{"id": "declared_resources", "kind": "file_exists"}], "tables": [], "figures": [], "attachments": [], "warnings": ["packaging_smoke_only"]}
        (base / "results" / "result.json").write_bytes(stable_json_bytes(result))
        refs = "；".join(f"#{qid}-{key.replace('_', '-')}" for key in metrics[qid])
        (base / "paper.typ").write_text(f'#import "../../paper/generated/results.typ": *\n= {qid.upper()}\n\n包装值：{refs}。\n', encoding="utf-8")
    (target_run / "paper" / "generated").mkdir(parents=True, exist_ok=True)
    (target_run / "paper" / "main.typ").write_text(_paper(), encoding="utf-8")
    (target_run / "source").mkdir(parents=True, exist_ok=True)
    _copy(report_path, target_run / "source" / report_path.name)
    return {"artifact_kind": SMOKE_KIND, "run_id": target_run.name, "question_count": 3}


def main() -> int:
    parser = argparse.ArgumentParser(description="2024-C packaging smoke only")
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--target-run", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source_run, args.target_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
