"""比赛验收、论文编译与提交包组装。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

from .result_ledger import load_json, load_question_configs, rebuild_ledger, stable_json_bytes, verification_status
from .typst_values import generate
from .verification import verify_question


EXCLUDED_PARTS = {".git", "__pycache__", ".venv", "cache", "tmp", "temp", ".pytest_cache", "review", "gates", "capability_evidence"}
EXCLUDED_PART_PREFIXES = ("review_handoff",)
EXCLUDED_SUFFIXES = {".tmp", ".temp", ".bak", ".pyc", ".pyo", ".key", ".pem"}
EXCLUDED_NAMES = {".env", "desktop.ini", "thumbs.db"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _issue(level: str, code: str, message: str, path: str | None = None) -> dict[str, str]:
    value = {"level": level, "code": code, "message": message}
    if path:
        value["path"] = path
    return value


def _compile(run_dir: Path, issues: list[dict[str, str]]) -> dict[str, Any]:
    source = run_dir / "paper" / "main.typ"
    output = run_dir / "paper" / "submission.pdf"
    if not source.is_file():
        issues.append(_issue("ERROR", "paper_source_missing", "缺少 paper/main.typ", "paper/main.typ"))
        return {"exit_code": None, "output": "paper/submission.pdf"}
    typst = shutil.which("typst")
    if not typst:
        issues.append(_issue("ERROR", "typst_missing", "未找到 Typst 编译器"))
        return {"exit_code": None, "output": "paper/submission.pdf"}
    completed = subprocess.run(
        [typst, "compile", "--root", str(run_dir), str(source), str(output)],
        cwd=run_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if completed.returncode != 0:
        issues.append(_issue("ERROR", "paper_compile_failed", completed.stderr.strip() or "Typst 编译失败", "paper/main.typ"))
    elif not output.is_file() or output.stat().st_size < 1024 or not output.read_bytes().startswith(b"%PDF"):
        issues.append(_issue("ERROR", "paper_pdf_invalid", "编译产物不是有效 PDF", "paper/submission.pdf"))
    return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "output": "paper/submission.pdf"}


def verify(run_dir: Path, mode: str = "contest_fast", *, compile_pdf: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    run_dir = run_dir.resolve()
    issues: list[dict[str, str]] = []
    if mode not in {"contest_fast", "contest_standard"}:
        raise ValueError(f"未知模式：{mode}")
    try:
        contest = load_json(run_dir / "contest.json")
    except Exception as exc:
        report = {"artifact_type": "contest_v2_verify_report", "mode": mode, "status": "failed", "issues": [_issue("ERROR", "contest_invalid", str(exc))]}
        (run_dir / "verify_report.json").write_bytes(stable_json_bytes(report))
        return report

    try:
        questions = load_question_configs(run_dir, contest)
    except Exception as exc:
        questions = []
        issues.append(_issue("ERROR", "questions_invalid", str(exc)))
    verification_summary: dict[str, str] = {}
    for question in questions:
        qid = str(question.get("id", "")).lower()
        result_path = run_dir / "questions" / qid / "results" / "result.json"
        if not result_path.is_file():
            level = "ERROR" if question.get("required", True) else "WARNING"
            issues.append(_issue(level, "result_missing", f"{qid} 缺少 result.json", result_path.relative_to(run_dir).as_posix()))
            continue
        try:
            verification = verify_question(run_dir, question, mode)
            result = load_json(result_path)
            state = verification_status(result, result_path.with_name("verification.json"))
            verification_summary[qid] = state
            if state != "verified":
                issues.append(_issue("ERROR", "verification_failed", f"{qid} 验证状态为 {state}"))
            if mode == "contest_standard":
                checks = verification["checks"]
                for check_id in question.get("recommended_checks", []):
                    if checks.get(str(check_id), {}).get("status") != "passed":
                        issues.append(_issue("WARNING", "recommended_check_missing", f"{qid} 缺少建议检查 {check_id}"))
        except Exception as exc:
            verification_summary[qid] = "failed"
            issues.append(_issue("ERROR", "result_or_checker_invalid", f"{qid}: {exc}"))

    try:
        ledger = rebuild_ledger(run_dir)
        generate(run_dir / "result_ledger.json", run_dir / "paper" / "generated" / "results.typ")
        for entry in ledger.entries:
            if entry.verification != "verified":
                issues.append(_issue("ERROR", "ledger_unverified", f"{entry.key} 状态为 {entry.verification}"))
    except Exception as exc:
        ledger = None
        issues.append(_issue("ERROR", "ledger_rebuild_failed", str(exc)))

    for question in questions:
        qid = str(question.get("id", "")).lower()
        base = run_dir / "questions" / qid
        for relative in ("model.md", "run.py", "paper.typ", "check.md"):
            path = base / relative
            if question.get("required", True) and (not path.is_file() or path.stat().st_size == 0):
                issues.append(_issue("ERROR", "question_artifact_missing", f"{qid} 缺少 {relative}", path.relative_to(run_dir).as_posix()))
        if ledger and (base / "paper.typ").is_file():
            body = (base / "paper.typ").read_text(encoding="utf-8", errors="replace")
            for entry in (item for item in ledger.entries if item.question_id == qid):
                variable = f"{qid}-{entry.metric_id.replace('_', '-')}"
                if variable not in body:
                    issues.append(_issue("WARNING", "metric_not_referenced", f"{qid} 正文未引用 {variable}"))

    for relative in contest.get("required_materials", []):
        if not (run_dir / str(relative)).is_file():
            issues.append(_issue("ERROR", "official_material_missing", f"缺少官方材料 {relative}", str(relative)))
    for relative in contest.get("required_attachments", []):
        if not (run_dir / str(relative)).is_file():
            issues.append(_issue("ERROR", "official_attachment_missing", f"缺少官方附件 {relative}", str(relative)))

    paper_source = run_dir / "paper" / "main.typ"
    if paper_source.is_file():
        main_text = paper_source.read_text(encoding="utf-8", errors="replace")
        for question in questions:
            qid = str(question["id"]).lower()
            include = f'../questions/{qid}/paper.typ'
            if include not in main_text:
                issues.append(_issue("ERROR", "question_paper_not_included", f"最终论文未包含 {qid} 问级正文", "paper/main.typ"))

    compile_record = _compile(run_dir, issues) if compile_pdf else {"exit_code": None, "skipped": True}
    errors = sum(item["level"] == "ERROR" for item in issues)
    warnings = sum(item["level"] == "WARNING" for item in issues)
    report = {
        "artifact_type": "contest_v2_verify_report",
        "contest_id": str(contest.get("contest_id", run_dir.name)),
        "mode": mode,
        "status": "passed" if errors == 0 else "failed",
        "verification": verification_summary,
        "ledger_entry_count": len(ledger.entries) if ledger else 0,
        "compile": compile_record,
        "summary": {"errors": errors, "warnings": warnings},
        "issues": issues,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "scope_note": "PASS 仅表示当前比赛提交检查通过，不代表资格认证或奖项水平。",
    }
    (run_dir / "verify_report.json").write_bytes(stable_json_bytes(report))
    return report


def _included(path: Path, run_dir: Path) -> bool:
    relative = path.relative_to(run_dir)
    lower_parts = {part.lower() for part in relative.parts}
    if lower_parts & EXCLUDED_PARTS:
        return False
    if any(part.lower().startswith(EXCLUDED_PART_PREFIXES) for part in relative.parts):
        return False
    if path.name.lower() in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name.startswith("~$") or path.name.endswith("~"):
        return False
    if relative.parts and relative.parts[0] == "package":
        return False
    return True


def package(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    report = load_json(run_dir / "verify_report.json")
    if report.get("status") != "passed":
        raise ValueError("verify 未通过，拒绝组装提交包")
    pdf = run_dir / "paper" / "submission.pdf"
    if not pdf.is_file():
        raise FileNotFoundError("缺少 paper/submission.pdf")
    output = run_dir / "package"
    output.mkdir(parents=True, exist_ok=True)
    submission = output / "submission.pdf"
    shutil.copy2(pdf, submission)
    files = sorted((path for path in run_dir.rglob("*") if path.is_file() and _included(path, run_dir)), key=lambda path: path.relative_to(run_dir).as_posix())
    support = output / "support.zip"
    with zipfile.ZipFile(support, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(run_dir).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return {
        "submission_pdf": submission.relative_to(run_dir).as_posix(),
        "support_zip": support.relative_to(run_dir).as_posix(),
        "submission_sha256": sha256_file(submission),
        "support_sha256": sha256_file(support),
        "support_file_count": len(files),
    }
