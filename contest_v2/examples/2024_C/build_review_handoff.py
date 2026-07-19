"""构建不包含作者过程信息的独立 Reviewer 交接包。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def require_current_paper_admission(run_dir: Path, paper_path: Path) -> dict[str, object]:
    """只允许已通过且绑定当前 PDF 的 submission candidate 进入独立评审。"""

    admission_path = run_dir / "review/paper_admission.json"
    if not admission_path.is_file():
        raise FileNotFoundError(f"缺少 Paper Admission：{admission_path}")
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    if admission.get("paper_admission") != "pass":
        raise ValueError("Paper Admission 未通过，当前论文只能继续作者侧大修")
    if admission.get("paper_type") != "submission_candidate":
        raise ValueError("paper_type 不是 submission_candidate，禁止构建 Reviewer 交接包")
    expected_digest = str(admission.get("pdf_sha256", "")).removeprefix("sha256:")
    actual_digest = sha256(paper_path)
    if expected_digest != actual_digest:
        raise ValueError("Paper Admission 已过期：记录的 PDF 摘要与当前论文不一致")
    return admission


def build(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.resolve()
    paper_path = run_dir / "paper/submission.pdf"
    admission = require_current_paper_admission(run_dir, paper_path)
    output = run_dir / "review_handoff_round2"
    output.mkdir(parents=True, exist_ok=True)
    copy(paper_path, output / "final_submission.pdf")
    copy(run_dir / "review/paper_admission.json", output / "paper_admission.json")
    copy(run_dir / "result_ledger.json", output / "result_ledger.json")
    copy(
        run_dir.parents[2] / "docs/contest_v2/NATIONAL_CONTEST_REVIEW_WORKFLOW.md",
        output / "NATIONAL_CONTEST_REVIEW_WORKFLOW.md",
    )
    copy(
        run_dir.parents[2] / "papers/EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json",
        output / "EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json",
    )
    figure_paths = [
        "questions/q1/figures/scenario_profit.png",
        "questions/q1/figures/resource_usage.png",
        "questions/q2/figures/candidate_scores.png",
        "questions/q2/figures/held_out_distribution.png",
        "questions/q2/figures/sample_convergence.png",
        "questions/q3/figures/demand_correlation.png",
        "questions/q3/figures/plan_changes.png",
        "questions/q3/figures/paired_difference.png",
    ]
    for relative in figure_paths:
        copy(run_dir / relative, output / "figures" / Path(relative).name)

    verification = {}
    for qid in ("q1", "q2", "q3"):
        value = json.loads((run_dir / f"questions/{qid}/results/verification.json").read_text(encoding="utf-8"))
        verification[qid] = {
            "question_id": qid,
            "checked_result_digest": value["checked_result_digest"],
            "checker": value["checker"],
            "checks": value["checks"],
        }
    report = json.loads((run_dir / "verify_report.json").read_text(encoding="utf-8"))
    verification_summary = {
        "artifact_type": "contest_v2_reviewer_verification_summary",
        "contest_id": report["contest_id"],
        "verify_status": report["status"],
        "verify_summary": report["summary"],
        "ledger_entry_count": report["ledger_entry_count"],
        "questions": verification,
        "scope_note": report["scope_note"],
    }
    (output / "verification_summary.json").write_text(json.dumps(verification_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    attachments = []
    for relative in ("official/result1_1.xlsx", "official/result1_2.xlsx", "official/result2.xlsx", "official/result3_supplement.xlsx"):
        path = run_dir / relative
        attachments.append({"path": relative, "required_by_problem": relative != "official/result3_supplement.xlsx", "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    (output / "official_attachment_inventory.json").write_text(json.dumps({"attachments": attachments}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_paths = [
        "questions/q2/results/tables/solver_evidence.csv",
        "questions/q2/results/tables/plan_difference.csv",
        "questions/q2/results/tables/bootstrap_intervals.csv",
        "questions/q2/results/tables/risk_weight_sensitivity.csv",
        "questions/q3/results/tables/solver_evidence.csv",
        "questions/q3/results/tables/plan_difference.csv",
        "questions/q3/results/tables/crop_relations.csv",
    ]
    for relative in evidence_paths:
        qid = Path(relative).parts[1]
        name = f"{Path(relative).stem}_{qid}.csv"
        copy(run_dir / relative, output / "evidence" / name)
    (output / "minimal_reproduction.md").write_text(
        """# 最小复现说明

输入仅为 `official_materials/2024_C` 官方题面、附件和模板。运行目录中的 `shared/solver_core.py` 是抽取的纯数据/MILP/评价/Excel 函数，不读取历史结果。

```powershell
python questions/q1/run.py
python questions/q2/run.py
python questions/q3/run.py
$env:PYTHONPATH='..\\..'
python ..\\..\\scripts\\contest.py verify . --mode contest_standard
python ..\\..\\scripts\\contest.py package .
```

预算：Q1 两个 MILP 各 60 秒；Q2 三个 64 情景风险 MILP 各最多 300 秒；Q3 三个 128 情景固定离散格局面积再分配各最多 180 秒；单进程 RSS 上限 4 GiB。Q2 使用 64x3/512/2048 样本，Q3 使用 128x3/512/2048 相关加 2048 独立对照；阶段 seed 不重叠。Q2 目标为 0.75 期望利润加 0.25 的 10% 左尾 CVaR，Q3 沿用该目标。Reviewer 不应读取作者对话、旧 Formal Result、旧 Gate、旧论文或首次评阅文件。
""",
        encoding="utf-8",
    )
    (output / "REVIEW_TASK_PROMPT.md").write_text(
        """# 第二轮独立 Final Reviewer 任务

你是 2024-C 完整提交物的独立 Final Reviewer。只读取本目录中的：

- `final_submission.pdf`
- `result_ledger.json`
- `verification_summary.json`
- `figures/`
- `evidence/`
- `official_attachment_inventory.json`
- `minimal_reproduction.md`
- `NATIONAL_CONTEST_REVIEW_WORKFLOW.md`
- `EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json`
- `paper_admission.json`

不要读取主实现任务对话、中间思考、旧 Formal Result、旧 Gate、旧论文、首次评阅文件、作者修补清单或同题优秀论文。必须按 `NATIONAL_CONTEST_REVIEW_WORKFLOW.md` 评审：使用优秀论文学习库抽象出的跨题高分论文画像，而不是只检查文件一致性。

这是修订后的第二轮提交物。请从最终产物本身重新审查。将结论写到运行目录的 `review/final_review_round2.md`，必须包含：

1. 必须修复；
2. 建议修复；
3. 可接受风险；
4. 模型正确性；
5. 结果可信性；
6. 图表有效性；
7. 论文完整性；
8. 六维 100 分内部评分与逐项证据；
9. 与优秀论文画像的差距；
10. 是否建议提交；
11. 仅作内部判断的优秀论文竞争力及不确定性说明。
12. 创新证据表：基线、实际贡献、题意依据、量化证据和适用边界；
13. 可读性缺陷：具体页码、对理解的影响和修改建议；
14. AI 痕迹风险：只给低/中/高、命中证据数、具体位置和修改建议，并声明这不是作者身份判断或 AI 生成概率。
15. 按固定 20/20/20/15/15/10 权重给分，并逐项核对总分、三个核心维度 14/20 下限、其他维度 60% 下限和 MUST；
16. 输出唯一结构化结论：`SUBMISSION_RECOMMENDED`、`MAJOR_REVISION` 或 `NOT_RECOMMENDED`。

不得修改任何资格状态，不得把 verify PASS 或 Paper Admission PASS 解释为资格认证或奖项水平。漏答、核心模型未写入论文、题意/单位错误、结果无法复算、优化缺少可信改进或搜索证据、数据泄漏、扩展摘要冒充论文、图表误导、用内部流程代替建模、夸大全局最优等阻断项不受总分抵消。若存在必须修复项，请给出具体页码、图号或 Ledger 键。
""",
        encoding="utf-8",
    )
    return {
        "handoff_dir": str(output),
        "pdf_sha256": sha256(output / "final_submission.pdf"),
        "ledger_sha256": sha256(output / "result_ledger.json"),
        "figure_count": len(figure_paths),
        "paper_admission_pdf_sha256": admission["pdf_sha256"],
        "review_output": str(run_dir / "review/final_review_round2.md"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.run_dir), ensure_ascii=False, indent=2))
