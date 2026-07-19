"""为任意 Contest v2 运行构建隔离的独立 Reviewer 交接包。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from contest_v2.paper_admission import require_current_paper_admission, sha256


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"交接资源不存在：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def safe_run_path(run_dir: Path, relative: str) -> Path:
    path = (run_dir / relative).resolve()
    if path != run_dir and run_dir not in path.parents:
        raise ValueError(f"资源路径越出运行目录：{relative}")
    return path


def build(run_dir: Path, round_number: int) -> dict[str, object]:
    run_dir = run_dir.resolve()
    repository_root = run_dir.parents[2]
    paper_path = run_dir / "paper/submission.pdf"
    registry_path = repository_root / "papers/EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json"
    workflow_path = repository_root / "docs/contest_v2/NATIONAL_CONTEST_REVIEW_WORKFLOW.md"
    admission = require_current_paper_admission(run_dir, paper_path, registry_path)
    contest = load_json(run_dir / "contest.json")
    question_ids = [str(qid) for qid in contest["question_ids"]]

    output = run_dir / f"review_handoff_round{round_number}"
    if output.exists():
        # 交接包是当前最终产物的快照，重建时禁止混入上一版文件。
        shutil.rmtree(output)
    output.mkdir(parents=True)

    fixed_files = {
        paper_path: output / "final_submission.pdf",
        run_dir / "review/paper_admission.json": output / "paper_admission.json",
        run_dir / "result_ledger.json": output / "result_ledger.json",
        run_dir / str(admission["learning_context_path"]): output / "learning_context.json",
        workflow_path: output / "NATIONAL_CONTEST_REVIEW_WORKFLOW.md",
        registry_path: output / "EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json",
    }
    for source, target in fixed_files.items():
        copy_file(source, target)

    verification_questions: dict[str, Any] = {}
    evidence_inventory: list[dict[str, Any]] = []
    for qid in question_ids:
        result_path = run_dir / f"questions/{qid}/results/result.json"
        verification_path = run_dir / f"questions/{qid}/results/verification.json"
        result = load_json(result_path)
        verification = load_json(verification_path)
        copy_file(result_path, output / f"evidence/questions/{qid}/result.json")
        copy_file(verification_path, output / f"evidence/questions/{qid}/verification.json")
        for group in ("tables", "figures"):
            resources = result.get(group, [])
            if not isinstance(resources, list):
                raise ValueError(f"{qid}.result.{group} 必须是列表")
            for resource in resources:
                if not isinstance(resource, dict) or not isinstance(resource.get("path"), str):
                    raise ValueError(f"{qid}.result.{group} 包含无效资源")
                relative = str(resource["path"])
                source = safe_run_path(run_dir, relative)
                target = output / "evidence" / relative
                copy_file(source, target)
                evidence_inventory.append(
                    {"question_id": qid, "kind": group, "path": relative, "size_bytes": source.stat().st_size, "sha256": sha256(source)}
                )
        verification_questions[qid] = {
            "checked_result_digest": verification.get("checked_result_digest"),
            "checker": verification.get("checker"),
            "checks": verification.get("checks"),
        }

    report = load_json(run_dir / "verify_report.json")
    verification_summary = {
        "artifact_type": "contest_v2_reviewer_verification_summary",
        "contest_id": report.get("contest_id"),
        "verify_status": report.get("status"),
        "verify_summary": report.get("summary"),
        "ledger_entry_count": report.get("ledger_entry_count"),
        "questions": verification_questions,
        "scope_note": report.get("scope_note"),
    }
    (output / "verification_summary.json").write_text(
        json.dumps(verification_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "evidence_inventory.json").write_text(
        json.dumps({"resources": evidence_inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    official_inventory: list[dict[str, Any]] = []
    official_paths = [*contest.get("required_materials", []), *contest.get("required_attachments", [])]
    for relative_value in official_paths:
        relative = str(relative_value)
        source = safe_run_path(run_dir, relative)
        target = output / "official_materials" / relative
        copy_file(source, target)
        official_inventory.append(
            {"path": relative, "size_bytes": source.stat().st_size, "sha256": sha256(source)}
        )
    (output / "official_material_inventory.json").write_text(
        json.dumps({"materials": official_inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    review_output = run_dir / f"review/final_review_round{round_number}.md"
    (output / "minimal_reproduction.md").write_text(
        f"""# 最小复现说明

运行 ID：`{run_dir.name}`；题目：`{contest.get('contest_id')}`；模式：`{contest.get('mode')}`。

```powershell
$env:PYTHONPATH='.'
python scripts/contest.py verify runs/{run_dir.name} --mode contest_standard
python scripts/contest.py package runs/{run_dir.name}
```

求解预算、材料冻结和同题排除范围见交接包内 `official_materials/reports/material_freeze.json` 与 `learning_context.json`。Reviewer 不读取作者对话、旧评阅或同题解答。
""",
        encoding="utf-8",
    )
    (output / "REVIEW_TASK_PROMPT.md").write_text(
        f"""# 第 {round_number} 轮独立 Final Reviewer 任务

你是 `{contest.get('contest_id')}` 完整提交物的独立 Final Reviewer。只读取本交接目录中的最终产物；不要读取作者任务对话、中间思考、旧论文、旧结果、旧 Gate、旧评阅、作者修补清单、同题优秀论文、同题题解、参考答案或同题专用代码。不得修改代码、结果、论文、Ledger、Verification、Admission 或 package。

先阅读 `NATIONAL_CONTEST_REVIEW_WORKFLOW.md`，按全国大学生数学建模竞赛参赛论文标准和仓库优秀论文学习库抽象出的跨题画像评审，而不是只检查文件一致性。`verification_summary.json` 和 `paper_admission.json` 只证明前置门禁，不能代替论文质量判断。

评阅必须包含：竞赛标准总评；六维固定权重评分及逐项页码/证据；优秀论文画像差距；必须修复、建议修复、可接受风险；模型正确性；求解和结果可信性；图表与论文完整性；创新证据表；可读性缺陷清单；AI 痕迹风险低/中/高、证据数和具体位置（明确声明不是作者身份或 AI 生成概率）；是否建议提交；竞争力及不确定性。最后只给一个结构化结论：`SUBMISSION_RECOMMENDED`、`MAJOR_REVISION` 或 `NOT_RECOMMENDED`，并逐项核对总分、三个核心维度 14/20、其他维度 60% 下限和 MUST 是否为空。

把完整评阅写入：

`{review_output}`

除该评阅文件外不得写入任何位置。
""",
        encoding="utf-8",
    )
    return {
        "handoff_dir": str(output),
        "review_output": str(review_output),
        "pdf_sha256": sha256(output / "final_submission.pdf"),
        "ledger_sha256": sha256(output / "result_ledger.json"),
        "question_ids": question_ids,
        "evidence_count": len(evidence_inventory),
        "official_material_count": len(official_inventory),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--round", type=int, default=1, dest="round_number")
    args = parser.parse_args()
    if args.round_number < 1:
        parser.error("--round 必须为正整数")
    print(json.dumps(build(args.run_dir, args.round_number), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
