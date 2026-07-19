"""Contest Production v2 的薄命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .result_ledger import ResultLedger
from .status import derive_status
from .typst_values import render_typst
from .verify_package import package, verify


_CHINESE_NUMERALS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


def _write_new(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _question_title(index: int) -> str:
    return f"问题{_CHINESE_NUMERALS[index - 1]}" if 0 < index <= len(_CHINESE_NUMERALS) else f"问题{index}"


def _paper_main(includes: str, standard: str) -> str:
    title = "全国大学生数学建模竞赛论文" if standard == "CUMCM_2026" else "数学建模竞赛论文"
    return f'''#import "generated/results.typ": *
#set page(paper: "a4", margin: 2.5cm, footer: context align(center)[#counter(page).display()])
#set text(lang: "zh", font: ("Noto Serif CJK SC", "Source Han Serif SC", "SimSun"))
#set par(justify: true)

= {title}

#align(center)[
  参赛队编号：待填写\\
  题目：待填写
]

== 摘要
本文针对题目给出的现实问题，建立可解释、可复算的数学模型，并通过独立检查、基线对照和边界分析验证结果。摘要应按问题逐项给出方法、核心数值和结论，定稿时删除本提示。

== 关键词
数学建模；优化；验证；敏感性分析

== 问题重述与分析
将题面要求转换为现实对象、决策变量、评价指标、约束和最终输出，说明各子问题之间的继承关系。

== 模型假设
逐条给出假设、题意依据、可能偏差及适用边界。

== 符号说明与数据处理
定义全文使用的变量、参数、单位、数据来源和预处理方法。

{includes}

== 模型评价与结论
总结模型优点、误差来源、求解限制、推广范围和对题目的最终回答，避免把局部或受限结果表述为全局最优。

== 参考文献
按统一格式列出真实可核验的来源。

== 支撑材料
列出 `support.zip` 中的运行入口、结果、验证记录、图表、官方附件和复现命令。

== AI 工具使用声明
如使用 AI 工具，仅说明其用于资料整理、代码辅助或语言润色；模型假设、程序、数据处理、结果核验和最终结论由作者负责。
'''


def _stage_reports(run_dir: Path) -> None:
    reports = {
        "MODEL_REVIEW.md": "MODEL_REVIEW: DRAFT\n\n作者完成模型假设、变量、目标函数、约束和推导后改为 READY；存在题意或公式问题时改为 REVISE。\n",
        "EXPERIMENT_REVIEW.md": "EXPERIMENT_REVIEW: PENDING\n\n完成运行、基线/对照、复算、稳定性或边界检查后改为 PASS；证据不足时改为 REVISE。\n",
        "PAPER_COHERENCE_REVIEW.md": "PAPER_COHERENCE_REVIEW: PENDING\n\n逐问正文、图表、Ledger 数字和结论闭合后改为 READY；缺少解释或可读性问题时改为 REVISE。\n",
    }
    for name, text in reports.items():
        _write_new(run_dir / "reports" / name, text)


def init_run(run_dir: Path, contest_id: str, questions: list[str], paper_standard: str = "CUMCM_2026") -> dict[str, object]:
    run_dir.mkdir(parents=True, exist_ok=True)
    declared = [
        {"id": qid.lower(), "title": _question_title(index), "required": True, "required_checks": [], "recommended_checks": []}
        for index, qid in enumerate(questions, 1)
    ]
    contest = {
        "version": "2.0",
        "contest_id": contest_id,
        "mode": "contest_standard",
        "paper_standard": paper_standard,
        "question_ids": [item["id"] for item in declared],
        "required_materials": [],
        "required_attachments": [],
    }
    _write_new(run_dir / "contest.json", json.dumps(contest, ensure_ascii=False, indent=2) + "\n")
    for question in declared:
        base = run_dir / "questions" / question["id"]
        _write_new(base / "question.json", json.dumps(question, ensure_ascii=False, indent=2) + "\n")
        _write_new(base / "model.md", f"# {question['title']}模型\n\nTODO\n")
        _write_new(base / "run.py", '"""本问计算入口。"""\n\nraise SystemExit(\'TODO: 实现计算入口\')\n')
        _write_new(base / "paper.typ", f'''#import "../../paper/generated/results.typ": *

= {question["title"]}

TODO：删除本提示并填入本问正式论证。

== 问题回应
明确回答本问要求，列出最终决策、方案或数值。

== 模型建立
给出变量、单位、目标函数、约束、推导和题意依据。

== 求解方法
说明算法输入、输出、停止条件、计算预算和可复现实验设置。

== 结果与解释
引用生成的 Ledger 数字、表格或图形，解释结果来源、取舍和决策意义。

== 验证与适用边界
报告基线、独立复算、误差/敏感性/边界检查，并说明模型局限。
''')
        _write_new(base / "check.md", f"# {question['title']}最小检查\n\nTODO\n")
        (base / "results" / "tables").mkdir(parents=True, exist_ok=True)
        (base / "figures").mkdir(parents=True, exist_ok=True)
    empty = ResultLedger(contest_id, [])
    if not (run_dir / "result_ledger.json").exists():
        empty.write(run_dir / "result_ledger.json")
    _write_new(run_dir / "paper" / "generated" / "results.typ", render_typst(empty))
    includes = "\n".join(f'#include "../questions/{item["id"]}/paper.typ"' for item in declared)
    _write_new(run_dir / "paper" / "main.typ", _paper_main(includes, paper_standard))
    _stage_reports(run_dir)
    return {"run_dir": str(run_dir.resolve()), "created": True, "questions": [item["id"] for item in declared], "paper_standard": paper_standard}


def _print_status(value: dict[str, object]) -> None:
    for qid, fields in value.get("questions", {}).items():
        for key, state in fields.items():
            print(f"{qid.upper()} {key:<16} {state}")
    print(f"ledger{'':<14} {value.get('ledger')}")
    print(f"results.typ{'':<10} {value.get('results_typ')}")
    print(f"paper PDF{'':<11} {value.get('paper_pdf')}")
    for path, state in value.get("attachments", {}).items():
        print(f"{path:<24} {state}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contest", description="Contest Production v2")
    sub = parser.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init")
    init_parser.add_argument("run_dir", type=Path)
    init_parser.add_argument("--contest-id", required=True)
    init_parser.add_argument("--questions", nargs="+", default=["q1"])
    init_parser.add_argument("--paper-standard", choices=("CUMCM_2026", "generic"), default="CUMCM_2026")
    for name in ("status", "verify", "package"):
        child = sub.add_parser(name)
        child.add_argument("run_dir", type=Path)
        if name == "verify":
            child.add_argument("--mode", choices=("contest_fast", "contest_standard"), default=None)
            child.add_argument("--no-compile", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "init":
        print(json.dumps(init_run(args.run_dir, args.contest_id, args.questions, args.paper_standard), ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        _print_status(derive_status(args.run_dir))
        return 0
    if args.command == "verify":
        contest = json.loads((args.run_dir / "contest.json").read_text(encoding="utf-8"))
        report = verify(args.run_dir, args.mode or contest.get("mode", "contest_standard"), compile_pdf=not args.no_compile)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "passed" else 1
    result = package(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
