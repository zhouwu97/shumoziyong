"""Contest Production v2 的薄命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .result_ledger import ResultLedger
from .status import derive_status
from .typst_values import render_typst
from .verify_package import package, verify


QUESTION_JSON = {"id": "q1", "title": "问题一", "required": True, "required_checks": [], "recommended_checks": []}


def _write_new(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init_run(run_dir: Path, contest_id: str, questions: list[str]) -> dict[str, object]:
    run_dir.mkdir(parents=True, exist_ok=True)
    declared = [QUESTION_JSON | {"id": qid.lower(), "title": f"问题{index}"} for index, qid in enumerate(questions, 1)]
    contest = {"version": "2.0", "contest_id": contest_id, "mode": "contest_fast", "question_ids": [item["id"] for item in declared], "required_materials": [], "required_attachments": []}
    _write_new(run_dir / "contest.json", json.dumps(contest, ensure_ascii=False, indent=2) + "\n")
    for question in declared:
        base = run_dir / "questions" / question["id"]
        _write_new(base / "question.json", json.dumps(question, ensure_ascii=False, indent=2) + "\n")
        _write_new(base / "model.md", f"# {question['title']}模型\n\nTODO\n")
        _write_new(base / "run.py", "\"\"\"本问计算入口。\"\"\"\n\nraise SystemExit('TODO: 实现计算入口')\n")
        _write_new(base / "paper.typ", f'#import "../../paper/generated/results.typ": *\n= {question["title"]}\n\nTODO\n')
        _write_new(base / "check.md", f"# {question['title']}最小检查\n\nTODO\n")
        (base / "results" / "tables").mkdir(parents=True, exist_ok=True)
        (base / "figures").mkdir(parents=True, exist_ok=True)
    empty = ResultLedger(contest_id, [])
    if not (run_dir / "result_ledger.json").exists():
        empty.write(run_dir / "result_ledger.json")
    _write_new(run_dir / "paper" / "generated" / "results.typ", render_typst(empty))
    includes = "".join(f'#include "../questions/{item["id"]}/paper.typ"\n' for item in declared)
    _write_new(run_dir / "paper" / "main.typ", '#import "generated/results.typ": *\n#set page(paper: "a4")\n= 比赛论文\n' + includes)
    return {"run_dir": str(run_dir.resolve()), "created": True, "questions": [item["id"] for item in declared]}


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
    for name in ("status", "verify", "package"):
        child = sub.add_parser(name)
        child.add_argument("run_dir", type=Path)
        if name == "verify":
            child.add_argument("--mode", choices=("contest_fast", "contest_standard"), default=None)
            child.add_argument("--no-compile", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "init":
        print(json.dumps(init_run(args.run_dir, args.contest_id, args.questions), ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        _print_status(derive_status(args.run_dir))
        return 0
    if args.command == "verify":
        contest = json.loads((args.run_dir / "contest.json").read_text(encoding="utf-8"))
        report = verify(args.run_dir, args.mode or contest.get("mode", "contest_fast"), compile_pdf=not args.no_compile)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "passed" else 1
    result = package(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
