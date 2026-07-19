"""从客观文件实时推导比赛状态。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .result_ledger import build_ledger, load_json, load_question_configs, stable_json_bytes, verification_status
from .typst_values import render_typst


def _file_state(path: Path, *, draft_marker: str | None = None) -> str:
    if not path.is_file():
        return "missing"
    if path.stat().st_size == 0:
        return "draft"
    text = path.read_text(encoding="utf-8", errors="replace")
    markers = (draft_marker,) if draft_marker else ("TODO", "DRAFT", "PENDING")
    if any(marker and marker in text for marker in markers):
        return "draft"
    return "ready"


def derive_status(run_dir: Path) -> dict[str, Any]:
    contest_path = run_dir / "contest.json"
    if not contest_path.is_file():
        return {"contest": "missing", "questions": {}, "ledger": "missing", "results_typ": "missing", "paper_pdf": "missing"}
    contest = load_json(contest_path)
    questions: dict[str, Any] = {}
    try:
        question_configs = load_question_configs(run_dir, contest)
    except Exception:
        question_configs = []
    for question in question_configs:
        qid = str(question["id"]).lower()
        base = run_dir / "questions" / qid
        result_path = base / "results" / "result.json"
        result_state = "missing"
        verify_state = "unchecked"
        if result_path.is_file():
            try:
                result = load_json(result_path)
                result_state = "ready"
                verify_state = verification_status(result, result_path.with_name("verification.json"))
            except Exception:
                result_state = "failed"
                verify_state = "failed"
        questions[qid] = {
            "model": _file_state(base / "model.md", draft_marker="TODO"),
            "runner": _file_state(base / "run.py"),
            "result": result_state,
            "verification": verify_state,
            "paper": _file_state(base / "paper.typ", draft_marker="TODO"),
            "check": _file_state(base / "check.md", draft_marker="TODO"),
        }
    ledger_path = run_dir / "result_ledger.json"
    ledger_state = "missing"
    expected = None
    try:
        expected = build_ledger(run_dir)
        if ledger_path.is_file():
            ledger_state = "ready" if ledger_path.read_bytes() == stable_json_bytes(expected.to_dict()) else "stale"
    except Exception:
        ledger_state = "failed" if ledger_path.is_file() else "missing"
    typ_path = run_dir / "paper" / "generated" / "results.typ"
    typ_state = "missing"
    if expected and typ_path.is_file():
        typ_state = "ready" if typ_path.read_text(encoding="utf-8") == render_typst(expected) else "stale"
    attachments = {str(path): ("ready" if (run_dir / str(path)).is_file() else "missing") for path in contest.get("required_attachments", [])}
    return {
        "contest": "ready",
        "questions": questions,
        "ledger": ledger_state,
        "results_typ": typ_state,
        "paper_pdf": _file_state(run_dir / "paper" / "submission.pdf"),
        "attachments": attachments,
    }
